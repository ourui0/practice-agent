from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
import os

OUT = os.path.abspath("output/pdf/常见构造全等三角形模型.pdf")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

font_candidates = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]
font_path = next(p for p in font_candidates if os.path.exists(p))
pdfmetrics.registerFont(TTFont("CN", font_path))

W, H = A4
INK = HexColor("#172033")
BLUE = HexColor("#2867C7")
LIGHT = HexColor("#EAF2FF")
MUTED = HexColor("#5C677D")

def line(c, p, q, width=2, color=INK, dash=None):
    c.setStrokeColor(color); c.setLineWidth(width)
    c.setDash(dash or [])
    c.line(p[0], p[1], q[0], q[1])
    c.setDash([])

def label(c, text, p, dx=0, dy=0):
    c.setFillColor(INK); c.setFont("CN", 14)
    c.drawCentredString(p[0]+dx, p[1]+dy, text)

def dot(c, p):
    c.setFillColor(INK); c.circle(p[0], p[1], 2.2, fill=1, stroke=0)

def seg(c, p, q, a, b, ad=(0,0), bd=(0,0), width=2):
    line(c,p,q,width); dot(c,p); dot(c,q); label(c,a,p,*ad); label(c,b,q,*bd)

def tick(c, p, q, n=1):
    import math
    mx,my=(p[0]+q[0])/2,(p[1]+q[1])/2
    dx,dy=q[0]-p[0],q[1]-p[1]; L=(dx*dx+dy*dy)**.5
    nx,ny=-dy/L,dx/L
    for i in range(n):
        off=(i-(n-1)/2)*6
        cx,cy=mx+dx/L*off,my+dy/L*off
        line(c,(cx-4*nx,cy-4*ny),(cx+4*nx,cy+4*ny),1.5,BLUE)

def wrap(c, text, x, y, maxw, size=12, leading=20, color=INK):
    c.setFont("CN", size); c.setFillColor(color)
    buf=""; yy=y
    for ch in text:
        if ch == "\n":
            c.drawString(x,yy,buf); buf=""; yy-=leading; continue
        if stringWidth(buf+ch,"CN",size)>maxw:
            c.drawString(x,yy,buf); buf=ch; yy-=leading
        else: buf+=ch
    if buf: c.drawString(x,yy,buf)
    return yy-leading

def base(c, i, title, subtitle):
    c.setFillColor(HexColor("#FFFFFF")); c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(BLUE); c.rect(0,H-78,W,78,fill=1,stroke=0)
    c.setFillColor(HexColor("#FFFFFF")); c.setFont("CN",22)
    c.drawString(42,H-49,f"{i:02d}  {title}")
    c.setFont("CN",10); c.drawRightString(W-42,H-47,"常见构造全等三角形模型")
    c.setFillColor(LIGHT); c.roundRect(38,325,W-76,330,12,fill=1,stroke=0)
    c.setFillColor(MUTED); c.setFont("CN",10); c.drawCentredString(W/2,310,subtitle)
    c.setStrokeColor(HexColor("#D7DEEA")); c.line(42,286,W-42,286)
    c.setFillColor(MUTED); c.setFont("CN",9); c.drawCentredString(W/2,24,f"第 {i} 页 / 共 10 页")

def body(c, construction, compare, reason, use):
    x=48; y=260
    rows=[("构造",construction),("比较",compare),("依据",reason),("用途",use)]
    for head,txt in rows:
        c.setFillColor(BLUE); c.setFont("CN",12); c.drawString(x,y,head)
        y=wrap(c,txt,x+48,y,W-145,12,20,INK)-7

def draw1(c):
    A=(W/2,610); B=(170,390); C=(W-170,390); D=(W/2,355)
    for p,q in [(A,B),(A,C),(B,D),(C,D),(A,D)]: line(c,p,q)
    for t,p,d in [("A",A,(0,10)),("B",B,(-12,-2)),("C",C,(12,-2)),("D",D,(0,-20))]: dot(c,p); label(c,t,p,*d)

def draw2(c):
    A=(W/2,615); B=(155,440); C=(W-155,440); D=(W/2,440); E=(W/2,355)
    for p,q in [(A,B),(A,C),(B,C),(A,E),(E,C)]: line(c,p,q)
    for t,p,d in [("A",A,(0,10)),("B",B,(-12,-2)),("C",C,(12,-2)),("D",D,(16,-2)),("E",E,(0,-20))]: dot(c,p); label(c,t,p,*d)
    tick(c,A,D); tick(c,D,E); tick(c,B,D,2); tick(c,D,C,2)

def draw3(c, extend=False):
    A=(W/2,605); B=(155,390); C=(W-155,390); D=(350 if not extend else W-100,390)
    for p,q in [(A,B),(A,C),(B,D),(A,D)]: line(c,p,q)
    for t,p,d in [("A",A,(0,10)),("B",B,(-12,-2)),("C",C,(0,-20)),("D",D,(10,-18))]: dot(c,p); label(c,t,p,*d)
    tick(c,B,D); tick(c,A,B)

def draw5(c):
    O=(405,470); A=(145,615); B=(145,325); P=(275,470); M=(306,525); N=(306,415)
    for p,q in [(O,A),(O,B),(O,P),(P,M),(P,N)]: line(c,p,q)
    for t,p,d in [("O",O,(15,-4)),("A",A,(-10,5)),("B",B,(-10,-15)),("P",P,(12,6)),("M",M,(-8,10)),("N",N,(-8,-18))]: dot(c,p); label(c,t,p,*d)

def draw6(c):
    A=(155,420); B=(W-155,420); M=(W/2,420); P=(W/2,610)
    for p,q in [(A,B),(P,A),(P,B),(P,M)]: line(c,p,q)
    for t,p,d in [("A",A,(-12,-15)),("B",B,(12,-15)),("M",M,(15,-15)),("P",P,(0,12))]: dot(c,p); label(c,t,p,*d)
    tick(c,A,M); tick(c,M,B)

def draw7(c):
    A=(150,610); C=(W-150,610); O=(W/2,485); D=(150,360); B=(W-150,360)
    line(c,A,B); line(c,C,D)
    for t,p,d in [("A",A,(-10,10)),("C",C,(10,10)),("O",O,(15,0)),("D",D,(-10,-18)),("B",B,(10,-18))]: dot(c,p); label(c,t,p,*d)
    tick(c,A,O); tick(c,O,B); tick(c,C,O,2); tick(c,O,D,2)

def draw8(c):
    A=(145,605); B=(W-145,605); D=(145,360); C=(W-145,360); O=(W/2,482)
    for p,q in [(A,B),(D,C),(A,C),(B,D)]: line(c,p,q)
    for t,p,d in [("A",A,(-10,10)),("B",B,(10,10)),("D",D,(-10,-18)),("C",C,(10,-18)),("O",O,(15,0))]: dot(c,p); label(c,t,p,*d)
    tick(c,A,O); tick(c,O,C)

def draw9(c):
    O=(W/2,445); A=(180,600); B=(440,445); C=(385,350)
    for p,q in [(O,A),(O,B),(O,C),(A,C),(B,C)]: line(c,p,q)
    for t,p,d in [("O",O,(-15,-15)),("A",A,(-8,12)),("B",B,(12,0)),("C",C,(8,-18))]: dot(c,p); label(c,t,p,*d)
    tick(c,O,A); tick(c,O,B)

def draw10(c):
    A=(W/2,610); B=(W/2,350); C=(430,480); D=(W-430,480)
    line(c,A,B,2,BLUE,[6,4]);
    for p,q in [(A,C),(B,C),(A,D),(B,D)]: line(c,p,q)
    for t,p,d in [("A",A,(0,12)),("B",B,(0,-20)),("C",C,(12,0)),("D",D,(-12,0))]: dot(c,p); label(c,t,p,*d)

models=[
 ("连接公共边模型","图示：连接 A、D，得到两个具有公共边的三角形。",draw1,"连接两个公共顶点 A、D。","△ABD 与 △ACD。","AD=AD，再结合题目给出的边或角，可用 SSS 或 SAS。","把分散条件集中到两个三角形中，是最优先考虑的辅助线。"),
 ("倍长中线模型","图示：延长中线 AD 到 E，使 DE=AD。",draw2,"已知 AD 是 △ABC 的中线，延长 AD 至 E，使 DE=AD，并连接 CE。","△ADB 与 △EDC。","AD=DE，BD=DC，∠ADB=∠EDC，由 SAS 得全等。","把中线转化为相等线段、平行关系或边的和差。"),
 ("截长模型","图示：在较长线段上截取 BD，使 BD=AB。",lambda c:draw3(c,False),"在较长的 BC 上取点 D，使 BD=AB，再连接 AD。","围绕 △ABD 寻找另一个三角形。","利用新造的 BD=AB，结合公共边或相等角，常用 SAS。","处理线段不等、边的和差及等腰三角形问题。"),
 ("补短模型","图示：延长较短线段 BC 至 D，使补长后的 BD=AB。",lambda c:draw3(c,True),"延长较短线段 BC 至 D，使 BD=AB，再连接 AD。","围绕 △ABD 寻找另一个三角形。","利用补出的相等线段，结合角关系或公共边证明全等。","与截长法合称“截长补短”，常用于证明线段和差。"),
 ("角平分线作垂线模型","图示：从角平分线上的点 P 向角的两边作垂线。",draw5,"点 P 在∠AOB的平分线上，作 PM⊥OA、PN⊥OB。","△OMP 与 △ONP。","∠OMP=∠ONP=90°，∠MOP=∠PON，OP=OP，由 AAS 得全等。","证明角平分线上的点到角两边距离相等。"),
 ("垂直平分线模型","图示：连接垂直平分线上的点 P 与线段两端点。",draw6,"M 是 AB 的中点，PM⊥AB，连接 PA、PB。","△PMA 与 △PMB。","AM=BM，PM=PM，∠PMA=∠PMB=90°，由 SAS 得全等。","得到 PA=PB，并处理线段垂直平分线问题。"),
 ("对顶角模型","图示：两条直线相交于 O，利用对顶角相等。",draw7,"连接或利用经过交点 O 的两组线段。","△AOC 与 △BOD。","若 AO=BO、CO=DO，且∠AOC=∠BOD，由 SAS 得全等。","看到相交线时，优先寻找对顶角作为相等角。"),
 ("平行线模型","图示：AB∥CD，交叉线相交于 O。",draw8,"利用已有平行线，或过某点作已知直线的平行线。","△AOB 与 △COD。","平行线给出内错角相等，对顶角也相等；再配合一组对应边，可用 ASA 或 AAS。","把角的关系转化为全等条件。"),
 ("旋转模型","图示：以 O 为中心旋转，使 OA 与 OB 对应。",draw9,"以公共顶点 O 为旋转中心，把一条线段按题目角度旋转到另一位置。","旋转前后的对应三角形。","旋转保持长度和角度不变，通常由 SAS 证明全等。","常用于等边三角形、正方形以及含 60°、90° 的问题。"),
 ("翻折（轴对称）模型","图示：以 AB 为对称轴，点 C 的对应点为 D。",draw10,"沿直线 AB 翻折，使点 C 与点 D 重合。","△ABC 与 △ABD。","轴对称保持对应线段和对应角相等，可用 SSS 或 SAS。","构造相等线段、相等角，处理角平分线与最短路径问题。"),
]

c=canvas.Canvas(OUT,pagesize=A4)
c.setTitle("常见构造全等三角形模型")
c.setAuthor("出题助手")
for i,(title,subtitle,drawer,construction,compare,reason,use) in enumerate(models,1):
    base(c,i,title,subtitle); drawer(c); body(c,construction,compare,reason,use); c.showPage()
c.save()
print(OUT)
