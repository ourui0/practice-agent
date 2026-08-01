from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointService,
)
from edu_exam_agent.application.services.teaching_package_service import (
    TeachingPackageRequest,
    TeachingPackageService,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import TeachingPackageModel
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def _response(evidence_id: str = "E1") -> dict:
    return {
        "status": "complete",
        "title": "一次函数教学设计",
        "basic_info": {},
        "material_tracking": {
            "knowledge_points": [
                {
                    "knowledge_point": "一次函数",
                    "role": "核心",
                    "teaching_level": "应用",
                    "evidence_ids": [evidence_id],
                    "source_summary": "一次函数的一般形式",
                    "page_references": [],
                }
            ],
            "coverage_matrix": [
                {
                    "knowledge_point": "一次函数",
                    "learning_objective_ids": ["O1"],
                    "student_task_ids": ["T1", "A1"],
                    "assessment_ids": ["A1"],
                    "evidence_ids": [evidence_id],
                }
            ],
            "unsupported_knowledge_points": [],
        },
        "learning_guide": {
            "document_name": "导学案",
            "learning_objectives": [
                {
                    "id": "O1",
                    "content": "能根据表达式识别一次函数",
                    "knowledge_points": ["一次函数"],
                    "success_criteria": "正确完成三道辨析题",
                }
            ],
            "key_points": ["一次函数的一般形式"],
            "difficult_points": ["理解k不等于0"],
            "prior_knowledge_check": [],
            "pre_class_preview": [],
            "knowledge_framework": [],
            "guided_fill_ins": [
                {
                    "id": f"B{index}",
                    "prompt": f"一次函数填空{index}：______。",
                    "answer": "y=kx+b",
                    "analysis": "根据教材中的一般形式填写。",
                    "knowledge_points": ["一次函数"],
                    "evidence_ids": [evidence_id],
                }
                for index in range(1, 7)
            ],
            "learning_tasks": [
                {
                    "id": "T1",
                    "title": "识别结构",
                    "task_type": "自主学习",
                    "scenario_or_material": "",
                    "questions": ["一次函数的一般形式是什么？"],
                    "learning_hint": "观察系数",
                    "student_output": "填写结构表",
                    "answer": "y=kx+b，且k不等于0。",
                    "analysis": "依据一次函数的一般形式回答。",
                    "knowledge_points": ["一次函数"],
                    "evidence_ids": [evidence_id],
                }
            ],
            "in_class_practice": [
                {
                    "id": "A1",
                    "question_type": "判断题",
                    "question": "y=2x+1是一次函数。",
                    "difficulty": "基础",
                    "knowledge_points": ["一次函数"],
                    "evidence_ids": [evidence_id],
                    "score": 5,
                    "answer": "正确",
                    "analysis": "该表达式符合一次函数的一般形式。",
                }
            ],
            "learning_summary": {
                "knowledge_structure": ["y=kx+b，k不等于0"],
                "student_reflection_prompts": ["我能否说明k的限制？"],
            },
            "knowledge_summary": [
                "一次函数的一般形式为y=kx+b，其中k不等于0。"
            ],
            "after_class_tasks": [],
        },
        "teaching_plan": {
            "document_name": "教案",
            "textbook_analysis": "教材给出一次函数的一般形式。",
            "student_analysis": "学生已有变量与函数基础。",
            "teaching_objectives": [
                {
                    "id": "O1",
                    "content": "能根据表达式识别一次函数",
                    "knowledge_points": ["一次函数"],
                    "assessment_method": "当堂判断",
                    "success_criteria": "正确完成三道辨析题",
                    "evidence_ids": [evidence_id],
                }
            ],
            "key_points": [],
            "difficult_points": [],
            "teaching_methods": ["问题引导"],
            "learning_methods": ["自主归纳"],
            "teaching_resources": ["教材"],
            "teaching_process": [
                {
                    "stage": "自主学习与检测",
                    "duration_minutes": 45,
                    "related_task_ids": ["T1", "A1"],
                    "teacher_activities": ["组织辨析"],
                    "student_activities": ["完成任务"],
                    "expected_student_responses": ["识别一般形式"],
                    "possible_difficulties": ["忽略k不等于0"],
                    "teacher_responses": ["提供反例"],
                    "assessment_id": "A1",
                    "assessment_method": "即时反馈",
                    "design_intention": "形成概念",
                    "knowledge_points": ["一次函数"],
                    "evidence_ids": [evidence_id],
                }
            ],
            "differentiated_instruction": {
                "support_for_struggling_students": [],
                "standard_requirements": [],
                "extension_for_advanced_students": [],
            },
            "board_design": ["y=kx+b，k不等于0"],
            "answer_reference": [
                {
                    "task_or_assessment_id": "A1",
                    "answer": "正确",
                    "solution_or_explanation": "符合一般形式。",
                    "scoring_criteria": ["判断正确得5分"],
                    "common_errors": [],
                    "correction_strategy": "",
                }
            ],
            "homework_design": [],
            "post_lesson_reflection_template": ["目标达成情况："],
        },
        "quality_check": {
            "all_knowledge_points_supported": True,
            "guide_and_plan_aligned": True,
            "lesson_time_total_minutes": 45,
            "lesson_time_matches": True,
            "answers_verified": True,
            "out_of_scope_content_found": False,
            "issues": [],
        },
        "insufficiencies": [],
    }


def _setup(tmp_path):
    engine = create_database_engine(tmp_path / "teaching.db")
    initialize_database(engine)
    course = CourseService(engine).create(
        CourseInput(
            name="八年级数学",
            subject="数学",
            education_stage="初中",
            grade="八年级",
            textbook_version="人教版",
        )
    )
    material = tmp_path / "八年级上册.md"
    material.write_text(
        "# 12.2 一次函数\n一次函数的一般形式是 y=kx+b，其中k不等于0。",
        encoding="utf-8",
    )
    documents = DocumentService(engine)
    document = documents.import_document(course.id, material)
    chapter = documents.list_chapters(document.id)[0]
    KnowledgePointService(engine).extract_candidates(course.id)
    point = KnowledgePointService(engine).list(course.id)[0]
    request = TeachingPackageRequest(
        course.id,
        document.id,
        (chapter.id,),
        (point.id,),
        lesson_duration_minutes=45,
    )
    return engine, request


def test_generates_tracks_and_persists_teaching_package(tmp_path) -> None:
    engine, request = _setup(tmp_path)
    service = TeachingPackageService(
        engine, FtsRetriever(engine), MockProvider(_response()), "mock"
    )

    result = service.generate(request)

    assert result.status == "complete"
    assert result.evidence and result.evidence[0].evidence_id == "E1"
    assert result.payload["quality_check"]["lesson_time_matches"] is True
    guide_text = service.render_learning_guide(result.payload)
    assert "一次函数" in guide_text
    assert "知识梳理填空" in guide_text
    assert "知识点总结" in guide_text
    assert "答案与解析" in guide_text
    assert guide_text.index("答案与解析") > guide_text.index("\n当堂练习\n")
    assert "难度：" not in guide_text
    assert "分值：" not in guide_text
    assert "题型：" not in guide_text
    assert "question_type" not in guide_text
    assert "B1  一次函数填空1：______。" in guide_text
    assert "\n  填空：" not in guide_text
    assert "\n\nB2  一次函数填空2：______。" in guide_text
    plan_text = service.render_teaching_plan(result.payload)
    assert "A1  答案：正确" in plan_text
    assert "•  A1" not in plan_text
    assert "task_or_assessment_id" not in plan_text
    assert "答案与解析" not in service.render_learning_guide(
        result.payload, include_answers=False
    )
    tracking_text = service.render_material_tracking(result.payload, result.evidence)
    assert "教材原文依据" in tracking_text
    assert "知识点1  一次函数" in tracking_text
    assert "对应关系1  一次函数" in tracking_text
    assert "教材证据：E1" in tracking_text
    assert "E1  《八年级上册.md》 12.2 一次函数（第1页）" in tracking_text
    assert "  对应知识点：一次函数" in tracking_text
    assert "  教材原文：" in tracking_text
    assert "•" not in tracking_text
    assert "page_references" not in tracking_text
    assert "evidence_ids" not in tracking_text
    loaded = service.load(result.record_id)
    assert loaded.payload == result.payload
    assert loaded.evidence == result.evidence
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TeachingPackageModel)) == 1


def test_rejects_invented_textbook_evidence_id(tmp_path) -> None:
    engine, request = _setup(tmp_path)
    service = TeachingPackageService(
        engine, FtsRetriever(engine), MockProvider(_response("E999")), "mock"
    )

    try:
        service.generate(request)
    except ValueError as exc:
        assert "不存在的教材证据编号" in str(exc)
    else:
        raise AssertionError("伪造教材证据的结果不得保存")

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TeachingPackageModel)) == 0


def test_marks_package_partial_when_practice_has_no_answer_reference(tmp_path) -> None:
    engine, request = _setup(tmp_path)
    response = _response()
    response["teaching_plan"]["answer_reference"] = []
    service = TeachingPackageService(
        engine, FtsRetriever(engine), MockProvider(response), "mock"
    )

    result = service.generate(request)

    assert result.status == "partial"
    assert result.payload["quality_check"]["answers_verified"] is False
    assert any(
        "缺少答案" in issue for issue in result.payload["quality_check"]["issues"]
    )


def test_reports_long_generation_timeout_in_teacher_friendly_language(tmp_path) -> None:
    engine, request = _setup(tmp_path)

    class _TimeoutProvider:
        def generate_json(self, _system_prompt, _user_prompt):
            raise TimeoutError("read timed out")

    service = TeachingPackageService(
        engine, FtsRetriever(engine), _TimeoutProvider(), "mock"
    )

    try:
        service.generate(request)
    except ValueError as exc:
        assert "模型在限定时间内没有生成完成" in str(exc)
    else:
        raise AssertionError("超时必须转换为教师可理解的错误提示")


def test_normalizes_empty_insufficiency_variants_from_model(tmp_path) -> None:
    engine, request = _setup(tmp_path)
    for raw_value in ({}, None, "无"):
        response = _response()
        response["insufficiencies"] = raw_value
        result = TeachingPackageService(
            engine, FtsRetriever(engine), MockProvider(response), "mock"
        ).generate(request)
        assert result.payload["insufficiencies"] == []


def test_normalizes_single_insufficiency_object_to_array(tmp_path) -> None:
    engine, request = _setup(tmp_path)
    response = _response()
    response["insufficiencies"] = {
        "type": "缺少图片信息",
        "description": "教材提到插图，但当前证据没有图片。",
        "affected_sections": "学习任务T2",
        "recommended_action": "补充对应教材页面。",
    }

    result = TeachingPackageService(
        engine, FtsRetriever(engine), MockProvider(response), "mock"
    ).generate(request)

    assert len(result.payload["insufficiencies"]) == 1
    assert result.payload["insufficiencies"][0]["affected_sections"] == [
        "学习任务T2"
    ]
