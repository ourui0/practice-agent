from __future__ import annotations

import json
import sqlite3
from pathlib import Path


database = Path.home() / "AppData" / "Roaming" / "EduExamAgent" / "edu_exam_agent.db"
connection = sqlite3.connect(database)
connection.row_factory = sqlite3.Row

courses = connection.execute(
    "SELECT id, name, grade, semester, textbook_version FROM courses ORDER BY id"
).fetchall()
documents = connection.execute(
    "SELECT id, course_id, filename, parse_status, chapter_count FROM documents ORDER BY id"
).fetchall()
chapters = connection.execute(
    """
    SELECT c.id, c.document_id, d.course_id, c.title, c.position
    FROM chapters c JOIN documents d ON d.id = c.document_id
    WHERE c.title LIKE '%四边形%' OR c.title LIKE '%平行四边形%'
       OR c.title LIKE '%矩形%' OR c.title LIKE '%菱形%' OR c.title LIKE '%正方形%'
    ORDER BY c.document_id, c.position
    """
).fetchall()
question_counts = connection.execute(
    """
    SELECT c.id AS chapter_id, c.title, q.difficulty, q.status, q.boundary_passed,
           COUNT(DISTINCT q.id) AS question_count
    FROM chapters c
    LEFT JOIN document_chunks dc ON dc.chapter_id = c.id
    LEFT JOIN question_sources qs ON qs.chunk_id = dc.id
    LEFT JOIN questions q ON q.id = qs.question_id
    WHERE c.title LIKE '%四边形%' OR c.title LIKE '%平行四边形%'
       OR c.title LIKE '%矩形%' OR c.title LIKE '%菱形%' OR c.title LIKE '%正方形%'
    GROUP BY c.id, q.difficulty, q.status, q.boundary_passed
    ORDER BY c.id, q.difficulty
    """
).fetchall()

print(
    json.dumps(
        {
            "database": str(database),
            "courses": [dict(row) for row in courses],
            "documents": [dict(row) for row in documents],
            "matching_chapters": [dict(row) for row in chapters],
            "question_counts": [dict(row) for row in question_counts],
        },
        ensure_ascii=False,
        indent=2,
    )
)
