"""주차바로 템플릿.pptx를 채워 포트폴리오 덱을 만든다.

사용법: python build_deck.py <템플릿.pptx> <출력.pptx>
템플릿의 서식은 그대로 두고 글자만 바꾼다. 이미지 자리의 점선 상자와 안내 문구는 지우고 assets/의 그림을 넣는다.
"""
import copy
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Pt

HERE = Path(__file__).parent
A = HERE / "assets"


# ---------- 도우미 ----------

def find(slide, sid, name=None):
    """템플릿은 슬라이드 번호 자리와 다른 도형이 같은 id(25)를 쓰므로, 이름 없이 찾을 때는 번호 자리를 뺀다."""
    hits = [s for s in slide.shapes if s.shape_id == sid and (name is None or s.name == name)]
    if name is None:
        hits = [s for s in hits if not s.name.startswith("Slide Number")]
    if len(hits) != 1:
        raise KeyError(f"shape id={sid} name={name}: {len(hits)}개")
    return hits[0]


def set_text(shape, text):
    """첫 run의 서식을 유지한 채 글자를 바꾼다. 줄바꿈(\n)은 같은 서식의 새 문단이 된다."""
    tf = shape.text_frame
    paras = tf.paragraphs
    first = paras[0]
    for p in paras[1:]:
        p._p.getparent().remove(p._p)
    runs = first.runs
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    lines = text.split("\n")
    runs[0].text = lines[0]
    # 한국어가 글자 단위로 끊기지 않고 띄어쓰기에서 줄이 바뀌게 한다 (언어를 한국어로 지정해야 적용된다).
    first._p.get_or_add_pPr().set("eaLnBrk", "0")
    rpr = runs[0]._r.get_or_add_rPr()
    rpr.set("lang", "ko-KR")
    rpr.set("altLang", "en-US")
    prev = first._p
    for line in lines[1:]:
        new = copy.deepcopy(first._p)
        prev.addnext(new)
        prev = new
        new_runs = new.findall("{http://schemas.openxmlformats.org/drawingml/2006/main}r")
        new_runs[0].find("{http://schemas.openxmlformats.org/drawingml/2006/main}t").text = line


def remove(shape):
    shape._element.getparent().remove(shape._element)


ALT = {
    "cover": "주차바로 앱 시작 화면, 회원가입 화면, 홈 화면",
    "admin-events": "관리자 웹 사건 목록과 사건 상세 패널",
    "admin-history": "관리자 웹 이력 관리 화면",
    "phone-dark": "다크 모드의 이동 요청 컴포넌트",
    "phone-light": "라이트 모드의 이동 요청 컴포넌트",
    "naming-mini": "색 이름 규칙 요소.톤.강조와 예시 토큰",
    "contrast-mini": "작업 전후 글자 대비 비교",
    "terminal-lint": "ESLint 색 규칙 오류와 경고 출력",
    "terminal-check": "대비 검사와 색 사용 횟수 출력",
}


def picture_fit(slide, path, x, y, w, h, name):
    """(x, y, w, h) pt 상자 안에 비율을 지켜 가운데 놓는다."""
    from PIL import Image
    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    pw, ph = iw * scale, ih * scale
    pic = slide.shapes.add_picture(str(path), Pt(x + (w - pw) / 2), Pt(y + (h - ph) / 2), Pt(pw), Pt(ph))
    pic.name = name
    pic._element.nvPicPr.cNvPr.set("descr", ALT[name])
    return pic


def set_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def solid_outline(shape):
    """점선 테두리를 실선으로 바꾼다 (휴대폰 틀)."""
    ln = shape._element.spPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}ln")
    if ln is None:
        return
    dash = ln.find("{http://schemas.openxmlformats.org/drawingml/2006/main}prstDash")
    if dash is not None:
        dash.set("val", "solid")


def link(shape, text, url):
    set_text(shape, text)
    shape.text_frame.paragraphs[0].runs[0].hyperlink.address = url


# ---------- 공통 머리글 (레이아웃) ----------

def fill_layouts(prs):
    for layout in prs.slide_layouts:
        for s in layout.shapes:
            if not s.has_text_frame:
                continue
            if s.text_frame.text == "LOGO":
                set_text(s, "주차바로")
            elif "서비스 한 줄 소개" in s.text_frame.text and s.text_frame.text.startswith("|"):
                set_text(s, "|   AI 불편 주차 감지 · 이동 요청 중계")


# ---------- 슬라이드별 내용 ----------

def slide1(sl):
    set_text(find(sl, 2), "주차바로")
    set_text(find(sl, 3), "AI가 불편 주차를 감지하고, 개인정보 없이 이동 요청을 중계하는 스마트 주차 관리 서비스")
    for sid in (4, 5, 6):
        remove(find(sl, sid))
    picture_fit(sl, A / "cover.png", 594.0, 64.8, 301.0, 237.6, "cover")
    rows = {
        9: "2026.07.06 ~ 2026.08.14 (6주)",
        11: "모바일 앱 (Expo · Android) / 관리자 웹",
        13: "7명 (FE 2 · BE 1 · AI·HW 4)",
        15: "팀장 · 프론트엔드 (관리자 웹 전담, 앱 화면)",
        18: "TypeScript",
        20: "React Native (Expo SDK 54), Vue 3",
        21: "상태 관리",
        22: "Pinia, React Context",
        24: "Docker, Jenkins, AWS EC2, Nginx",
        26: "REST (공통 응답 포맷), Expo Push",
        28: "GitLab, Jira, Figma, Notion",
    }
    for sid, text in rows.items():
        set_text(find(sl, sid), text)
    set_notes(sl, "주차바로는 AI가 아파트 주차장의 불편 주차를 감지하고, 차주의 개인정보를 드러내지 않고 이동 요청을 중계하는 서비스입니다. "
                  "7명 팀에서 팀장과 프론트엔드를 맡았고, 관리자 웹은 처음부터 맡아 만들었고 입주민 앱은 팀원과 화면을 나눠 개발했습니다. "
                  "앞의 두 포인트는 프로젝트 중에 한 일, 뒤의 두 포인트는 프로젝트가 끝난 뒤 회고에서 찾아 개선한 일입니다.")


def point_common(sl, label, title, sub, problem, solution, result):
    set_text(find(sl, 4, "Text 2"), label)
    set_text(find(sl, 2), title)
    set_text(find(sl, 3), sub)
    set_text(find(sl, 8, "Text 5"), problem)
    set_text(find(sl, 12, "Text 8"), solution)
    r = find(sl, 16, "Text 11")
    set_text(r, result)
    r.height = Pt(66)  # 성과는 세 줄까지


def slide2(sl):
    point_common(
        sl, "POINT 01", "관리자 사건 처리 화면", "AI 감지 사건을 관리자가 최종 판단하도록",
        "AI 자동 감지에는 오탐이 섞여, 관리자가 사건을 확인하고 처리할 화면이 필요했다",
        "Vue 3 관리자 웹을 맡아 사건 확인·오탐·완료 처리와 진행 이력을 구현했다",
        "화면 7개를 만들고 사건·구역 API를 연동해 배포했다. 자동 감지 요청과 입주민 요청도 구분해 보여준다",
    )
    for sid in (18, 19, 20, 21):
        remove(find(sl, sid))
    picture_fit(sl, A / "admin-events.png", 486.0, 68.4, 409.0, 349.2, "admin-events")
    set_text(find(sl, 22), "사건 목록과 상세 패널 · 확인이 필요한 사건을 한 화면에서 처리")
    set_notes(sl, "AI가 자동으로 사건을 만들지만 오탐이 섞일 수 있어서, 최종 판단은 관리자가 합니다. "
                  "관리자 웹을 Vue 3, Pinia로 처음부터 맡아 스플래시·로그인·사건 목록·사건 상세·주차 구역 관리·이력·설정 7개 화면을 만들었습니다. "
                  "사건 상세에서 관리자 확인, 오탐 처리, 완료 처리, 처리 메모와 진행 이력을 다루고, 사건·구역 API를 붙여 배포했습니다.")


def slide3(sl):
    point_common(
        sl, "POINT 02", "테이블 화면 공용화", "세 화면의 중복 로직을 한 곳으로",
        "사건 목록·이력·구역 관리 화면이 필터, 페이지네이션, CSV 내보내기를 각자 구현했다",
        "로직은 composable로, 검색창·표·페이지 하단 등은 공용 컴포넌트 7개로 추출했다",
        "세 화면 파일이 2,006줄에서 1,220줄로 줄고, 같은 수정을 한 곳에서 하게 됐다",
    )
    for sid in (19, 20, 21):
        remove(find(sl, sid))
    remove(find(sl, 18, "image-slot"))
    picture_fit(sl, A / "admin-history.png", 486.0, 64.8, 409.0, 280.8, "admin-history")
    set_text(find(sl, 23, "Text 16"), "39%")
    set_text(find(sl, 24, "Text 17"), "세 화면 파일 코드 감소\n2,006 → 1,220줄")
    set_text(find(sl, 26, "Text 19"), "7개")
    set_text(find(sl, 27, "Text 20"), "추출한 공용 UI 컴포넌트\nSearchBox · DataTable 등")
    set_notes(sl, "사건 목록, 이력 관리, 주차 구역 관리 세 화면이 비슷한 표를 갖고 있었는데 필터·페이지네이션·CSV 내보내기를 화면마다 따로 구현하고 있었습니다. "
                  "페이지네이션과 CSV는 공용 composable로, 화면별 필터는 각 기능의 composable로 옮기고, 검색창·표·상태 행·페이지 하단·필터 칩 등을 공용 컴포넌트 7개로 뽑았습니다. "
                  "세 화면 파일은 2,006줄에서 1,220줄로 줄었습니다. 전체 코드가 줄었다기보다 로직이 한 곳으로 모였다는 의미입니다.")


def slide4(sl):
    point_common(
        sl, "POINT 03", "테마를 받는 스타일 구조", "회고에서 찾은 다크 모드 미동작 원인 해결",
        "화면이 토큰 대신 팔레트를 463회 직접 써서(토큰은 26회) 다크 모드가 반만 동작했다",
        "고정 스타일 파일을 토큰을 받는 함수 createStyles(t)로 바꾸고 화면 단위로 켰다",
        "이동 요청 기능의 팔레트 직접 사용 130→0, 하드코딩 86→0. 이동 요청 화면 5개가 다크 모드를 지원한다",
    )
    slot = find(sl, 18, "image-slot")
    solid_outline(slot)
    for sid in (19, 20):
        remove(find(sl, sid))
    picture_fit(sl, A / "phone-dark.png", 512.0, 87.2, 189.2, 383.6, "phone-dark")
    set_text(find(sl, 24, "Text 17"), "고정 스타일")
    set_text(find(sl, 25, "Text 18"), "한 번 만들어지는 StyleSheet라 테마 훅을 못 씀")
    set_text(find(sl, 30, "Text 22"), "createStyles(t)")
    set_text(find(sl, 31, "Text 23"), "모드별로 한 번 만들어 재사용, 새 의존성 없음")
    set_notes(sl, "프로젝트가 끝나고 회고하면서 앱을 다크 모드로 켜 보니 화면 대부분이 라이트로 남아 있었습니다. "
                  "색 사용을 세어 보니 테마 토큰은 26회, 팔레트 직접 사용은 463회였습니다. 원인은 StyleSheet.create로 한 번 만들어지는 스타일 파일이 테마 훅을 쓸 수 없다는 구조였습니다. "
                  "스타일 파일이 토큰을 받는 함수 createStyles(t)를 내보내고, useThemedStyles가 모드별로 한 번만 만들어 재사용하게 했습니다. "
                  "기능 하나를 끝까지 옮기기로 범위를 정해, 색 참조가 가장 많은 이동 요청 기능(팀원이 만든 기능)을 옮겼습니다.")


def slide5(sl):
    point_common(
        sl, "POINT 04", "용도 기반 색 토큰", "이름은 쓰임새로, 대비는 자동 검사로",
        "같은 오류색이 네 가지 값으로 흩어졌고, 37개 조합 중 24개가 대비 기준 미달이었다",
        "요소.톤.강조 규칙으로 토큰을 다시 짓고, 미달 색은 같은 계열의 통과 값으로 옮겼다",
        "대비 미달 0 (라이트·다크 각 39개 조합). 린트와 대비 검사로 같은 실수가 다시 들어오지 못한다",
    )
    phone = find(sl, 18, "image-slot")
    solid_outline(phone)
    for sid in (19, 20, 23, 24, 27, 28):
        remove(find(sl, sid))
    remove(find(sl, 22, "image-slot"))
    remove(find(sl, 26, "image-slot"))
    picture_fit(sl, A / "phone-light.png", 494.0, 87.2, 178.4, 387.2, "phone-light")
    picture_fit(sl, A / "naming-mini.png", 702.0, 61.2, 194.4, 169.2, "naming-mini")
    picture_fit(sl, A / "contrast-mini.png", 702.0, 284.4, 194.4, 169.2, "contrast-mini")
    set_text(find(sl, 25, "Text 17"), "이름 규칙 · 요소.톤.강조")
    set_text(find(sl, 29, "Text 20"), "대비 미달 24 → 0")
    set_notes(sl, "색 이름을 orange600 같은 팔레트 이름이 아니라 요소.톤.강조로 지었습니다. text.error는 오류 글자, fill.brand.weak는 옅은 브랜드 면입니다. "
                  "글자와 아이콘은 실제로 놓이는 배경 위에서 WCAG AA(글자 4.5, 아이콘 3)를 넘게 했고, 옛 값으로 검사하면 37개 조합 중 24개가 미달이었습니다. "
                  "src/styles 밖에서 색 값을 적으면 린트가 막고, npm run check:contrast가 토큰 값을 직접 읽어 라이트·다크 39개씩 검사합니다.")


def slide6(sl):
    set_text(find(sl, 2), "규칙은 도구에 둔다")
    set_text(find(sl, 3), "종료 후 회고에서 문제를 직접 찾아 개선")
    set_text(find(sl, 8, "Text 5"), "끝난 앱을 다크 모드로 켜 보고, 색을 쓰는 방식을 세어 원인을 구조에서 찾았다")
    set_text(find(sl, 12, "Text 8"), "구조가 막으면 토큰은 쓰이지 않고, 규칙은 문서보다 도구에 있어야 지켜진다")
    r = find(sl, 16, "Text 11")
    set_text(r, "범위를 기능 하나로 끊어 끝까지 옮기고, 남은 곳은 린트 경고 146개로 드러냈다")
    r.height = Pt(66)
    for sid in (18, 19, 20, 23, 24, 25):
        remove(find(sl, sid))
    remove(find(sl, 17, "image-slot"))
    remove(find(sl, 22, "image-slot"))
    picture_fit(sl, A / "terminal-lint.png", 486.0, 64.8, 288.0, 205.2, "terminal-lint")
    picture_fit(sl, A / "terminal-check.png", 607.0, 284.4, 288.0, 198.0, "terminal-check")
    set_text(find(sl, 21, "Text 15"), "린트 · 옮긴 곳은 오류, 나머지는 경고")
    set_text(find(sl, 26, "Text 19"), "대비 자동 검사")
    set_notes(sl, "회고에서 가장 크게 배운 점은, 토큰을 만들어 두는 것만으로는 쓰이지 않는다는 것입니다. 구조가 막고 있으면 사람은 값을 직접 적게 됩니다. "
                  "또 이 작업 중에 eslint.config.ts의 규칙이 처음부터 적용되지 않고 있었다는 것도 찾았습니다. 문서에만 있는 규칙은 지켜지지 않습니다. "
                  "그래서 규칙을 린트와 대비 검사로 옮겼고, 앱 전체를 한 번에 바꾸는 대신 기능 하나를 끝까지 옮긴 뒤 나머지는 경고로 남겨 다음 작업 목록으로 삼았습니다.")


def slide7(sl):
    set_text(find(sl, 5, "Text 3"), "프로젝트 시작 · 팀장, 프론트엔드")
    set_text(find(sl, 6, "Text 4"), "2026.07.06")
    set_text(find(sl, 8, "Text 6"), "구현 완료 · 입주민 앱, 관리자 웹")
    set_text(find(sl, 9, "Text 7"), "2026.08.14")
    set_text(find(sl, 11, "Text 9"), "회고 후 디자인 시스템 개선")
    set_text(find(sl, 12, "Text 10"), "2026.11.26")

    # GitHub, 시연 영상 줄은 지우고 나머지 세 줄을 위로 올린다
    for sid in range(13, 23):
        remove(find(sl, sid))
    shift = Pt(174.2 - 100.8) * 2
    for sid in range(23, 38):
        s = find(sl, sid)
        s.top = s.top - shift
    set_text(find(sl, 26, "Text 21"), "Android 앱")
    link(find(sl, 27, "Text 22"), "APK 내려받기 (Google Drive)",
         "https://drive.google.com/drive/folders/1m4rUBzDPmmm41PEe1OWc4jHygtWS2sUb?usp=sharing")
    set_text(find(sl, 31, "Text 25"), "관리자 웹")
    link(find(sl, 32, "Text 26"), "i15e202.p.ssafy.io/admin", "https://i15e202.p.ssafy.io/admin/")
    set_text(find(sl, 36, "Text 29"), "팀 문서")
    link(find(sl, 37, "Text 30"), "Notion · 기획·API 명세",
         "https://app.notion.com/p/SSAFY-2-1-396967bab5a4804faef3f3def764090a?source=copy_link")
    set_notes(sl, "2026년 7월 6일부터 8월 14일까지 6주 동안 개발했고, 프로젝트가 끝난 뒤 11월에 회고하면서 디자인 시스템을 개선했습니다. "
                  "오른쪽은 앱 설치 파일, 관리자 웹, 팀 문서 링크입니다.")


def main(template, out):
    prs = Presentation(template)
    fill_layouts(prs)
    s = prs.slides
    slide1(s[0]); slide2(s[1]); slide3(s[2]); slide4(s[3]); slide5(s[4]); slide6(s[5]); slide7(s[6])
    prs.save(out)
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
