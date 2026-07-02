import streamlit as st
import kiwipiepy
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import re
from PIL import Image, ImageDraw, ImageFont
import io
import os

# --- 1. 페이지 설정 ---
st.set_page_config(layout="wide", page_title="AI 윤리문 작성하기")

# --- 2. 보안: 비밀 금고(Secrets) 안전 연동 ---
try:
    TEACHER_API_KEY = st.secrets["KOREAN_API_KEY"]
except Exception:
    TEACHER_API_KEY = None

if "left_passive" not in st.session_state: st.session_state.left_passive = ""
if "left_quote" not in st.session_state: st.session_state.left_quote = ""
if "right_content" not in st.session_state: st.session_state.right_content = ""

def clear_text(key):
    st.session_state[key] = ""

@st.cache_resource
def load_kiwi():
    return kiwipiepy.Kiwi()

kiwi = load_kiwi()

PASSIVE_COLOR = "<span style='background-color: #ffcccc; padding: 2px 4px; border-radius: 4px; font-weight: bold;'>{text}</span>"
DIRECT_COLOR = "<span style='background-color: #cce5ff; padding: 2px 4px; border-radius: 4px; font-weight: bold;'>{text}</span>"
INDIRECT_COLOR = "<span style='background-color: #d4edda; padding: 2px 4px; border-radius: 4px; font-weight: bold;'>{text}</span>"
CAUSATIVE_COLOR = "<span style='background-color: #e2e3e5; padding: 2px 4px; border-radius: 4px; font-weight: bold;'>{text}</span>"

def check_dict_api(word):
    if not TEACHER_API_KEY: return []
    url = f"https://stdict.korean.go.kr/api/search.do?key={TEACHER_API_KEY}&q={urllib.parse.quote(word)}"
    try:
        req = urllib.request.Request(url)
        res = urllib.request.urlopen(req)
        xml_data = res.read().decode('utf-8')
        root = ET.fromstring(xml_data)
        pos_tags = []
        for item in root.findall('.//item'):
            def_el = item.find('.//sense/definition')
            def_text = def_el.text.strip() if def_el is not None and def_el.text else ""
            if "피동사" in def_text: pos_tags.append("피동사")
            elif "사동사" in def_text: pos_tags.append("사동사")
            else: pos_tags.append("일반등재") 
        return pos_tags
    except Exception:
        return []

def is_yang_vowel(word_chunk):
    if not word_chunk: return False
    last_char = word_chunk[-1]
    if '가' <= last_char <= '힣':
        char_code = ord(last_char) - ord('가')
        return (char_code % 588) // 28 in [0, 2, 8, 9, 12] 
    return False

# --- 3. 안정성: 스트림릿 서버에서도 깨지지 않는 한글 폰트 로더 ---
@st.cache_resource
def get_korean_font(size=20):
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        try:
            urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf", font_path)
        except Exception: pass
    try:
        return ImageFont.truetype(font_path, size)
    except:
        return ImageFont.load_default()

def create_final_png(team_name, content, highlight_indices, p_intents, q_intents):
    img = Image.new("RGB", (800, 750), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    ftitle, fsub, fbody = get_korean_font(28), get_korean_font(20), get_korean_font(18)
    
    draw.rectangle([(20, 20), (780, 730)], outline=(100, 100, 100), width=3)
    draw.text((40, 40), "🏆 AI 윤리문 모둠 최종 결과물", fill=(30, 30, 30), font=ftitle)
    draw.text((40, 95), f"모둠명: {team_name}", fill=(50, 50, 200), font=fsub)
    draw.line([(40, 130), (760, 130)], fill=(0, 0, 0), width=2)
    
    y_pos = 150
    draw.text((40, y_pos), "📌 [표현 사용 의도]", fill=(0, 102, 204), font=fsub)
    y_pos += 35
    p_text = "• 피동 표현 의도: " + (", ".join(p_intents) if p_intents else "선택 안 함")
    draw.text((40, y_pos), p_text, fill=(50, 50, 50), font=fbody)
    y_pos += 30
    q_text = "• 인용 표현 의도: " + (", ".join(q_intents) if q_intents else "선택 안 함")
    draw.text((40, y_pos), q_text, fill=(50, 50, 50), font=fbody)
    y_pos += 50
    draw.line([(40, y_pos), (760, y_pos)], fill=(200, 200, 200), width=1)
    
    y_pos += 25
    draw.text((40, y_pos), "📝 [최종 윤리 홍보문]", fill=(0, 102, 204), font=fsub)
    y_pos += 40
    
    x = 40
    line_height = 32
    for idx, char in enumerate(content):
        if char == '\n':
            x = 40; y_pos += line_height; continue
            
        try: char_w = fbody.getlength(char)
        except: char_w = draw.textlength(char, font=fbody)
            
        if x + char_w > 760:
            x = 40; y_pos += line_height
            
        bg_color = highlight_indices.get(idx, None)
        if bg_color:
            draw.rectangle([x, y_pos-2, x+char_w, y_pos+line_height+2], fill=bg_color)
            
        draw.text((x, y_pos), char, fill=(0,0,0), font=fbody)
        x += char_w
    
    draw.text((40, 690), "* 본 결과물은 AI 윤리문 작성 프로그램을 통해 검증 완료되었습니다.", fill=(150, 150, 150), font=get_korean_font(14))
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def analyze_and_highlight(text, check_mode):
    if not text.strip(): return False, "문장을 입력해 주세요.", [], "", "", {}
    
    tokens = kiwi.tokenize(text)
    display_html, base_forms = [], []
    found_passive, found_quote = False, False
    error_msg = ""
    warning_msg = "" 
    last_verb_stem = ""
    last_verb_tag = ""
    highlight_indices = {}

    def mark_highlight(token_list, color_rgb):
        for t in token_list:
            for c in range(t.start, t.start + t.len):
                highlight_indices[c] = color_rgb

    spacing_error = bool(re.search(r'["”]\s+라고', text))
    if check_mode in ['quote', 'all'] and spacing_error:
        error_msg += "🚨 [띄어쓰기 오류] 큰따옴표 뒤의 '라고'는 조사이므로 앞말에 꼭 붙여 써야 합니다.\n\n"

    i = 0
    while i < len(tokens):
        token = tokens[i]
        form, tag = token.form, token.tag
        
        if tag in ['SF', 'SP'] or form in ['.', ',', '!', '?']:
            i += 1; continue

        if tag in ['VV', 'VA', 'VX', 'XSV', 'XSA', 'VCP', 'VCN']:
            last_verb_stem = form
            last_verb_tag = tag

        if tag in ['EP', 'EC', 'EF'] and form in ['았', '었', '였', '아', '어', '여']:
            prev_form = tokens[i-1].form if i > 0 else ""
            if prev_form.endswith('하'):
                form = '였' if form in ['았', '었', '였'] else '여'
            elif prev_form.endswith('시'):
                form = '었' if form in ['았', '었', '였'] else '어'
            elif is_yang_vowel(prev_form):
                form = '았' if form in ['았', '었', '였'] else '아'
            else:
                form = '었' if form in ['았', '었', '였'] else '어'

        if i < len(tokens) - 1 and tag == 'EC' and form in ['어', '아', '여'] and tokens[i + 1].tag == 'VX' and tokens[i + 1].form == '지':
            j_vowel = form 
            prev_form = tokens[i-1].form if i > 0 else ""
            prev_tag = tokens[i-1].tag if i > 0 else ""
            
            prev_verb_stem = ""
            ti = i - 1
            while ti >= 0 and tokens[ti].tag in ['VV', 'VA', 'VX', 'XSV', 'XSA']:
                prev_verb_stem = tokens[ti].form + prev_verb_stem
                ti -= 1

            is_double_passive_dict = False
            if TEACHER_API_KEY and prev_verb_stem:
                plist = check_dict_api(prev_verb_stem + "다")
                if '피동사' in plist:
                    is_double_passive_dict = True
            
            is_ha_verb = last_verb_stem.endswith('하') or last_verb_stem.endswith('해') or prev_form.endswith('하') or prev_form.endswith('해')
            is_adj = last_verb_tag in ['VA', 'XSA'] or prev_tag in ['VA', 'XSA']
            is_double = last_verb_stem.endswith('되') or last_verb_stem.endswith('되어') or prev_form.endswith('되') or prev_form.endswith('되어') or prev_form.endswith('돼')

            if is_adj:
                display_html.append(PASSIVE_COLOR.format(text=f"-{j_vowel}지다(상태변화)"))
                if check_mode in ['passive', 'all']:
                    error_msg += f"🚨 형용사에 '-어지다'가 결합한 것은 피동이 아니라 '상태 변화'입니다. 동사를 사용하세요.\n\n"
            elif is_ha_verb:
                display_html.append(PASSIVE_COLOR.format(text=f"-{j_vowel}지다(비문)"))
                if check_mode in ['passive', 'all']:
                    error_msg += "🚨 '-하다'로 끝나는 말은 '-해지다(하여지다)' 대신 '-되다'를 쓰는 것이 자연스럽습니다. (예: 사용해지다 ❌ -> 사용되다 ⭕)\n\n"
            elif is_double_passive_dict:
                found_passive = True 
                display_html.append(PASSIVE_COLOR.format(text=f"-{j_vowel}지다(이중피동 주의)").replace("#ffcccc", "#ffe6cc"))
                if check_mode in ['passive', 'all']:
                    wrong_word = prev_verb_stem + j_vowel + "지다"
                    correct_word = prev_verb_stem + "다"
                    warning_msg += f"💡 '{correct_word}'는 이미 피동사인데 '-어지다'가 불필요하게 또 붙은 '이중 피동'입니다. 국어 문법상 틀린 표현이니 '{correct_word}'로 고치는 것을 강력히 추천합니다! (일단 저장은 가능합니다)\n\n"
                mark_highlight([tokens[i], tokens[i+1]], (255, 230, 153))
            
            elif is_double:
                found_passive = True 
                display_html.append(PASSIVE_COLOR.format(text=f"-{j_vowel}지다(이중피동 주의)").replace("#ffcccc", "#ffe6cc"))
                if check_mode in ['passive', 'all']:
                    warning_msg += "💡 '-되다'에 '-어지다'가 또 붙은 '이중 피동'입니다. 국어 문법상 틀린 표현이니 고치는 것을 추천합니다! (일단 저장은 가능합니다)\n\n"
                mark_highlight([tokens[i], tokens[i+1]], (255, 230, 153))
            else:
                found_passive = True
                display_html.append(PASSIVE_COLOR.format(text=f"-{j_vowel}지다(피동)"))
                mark_highlight([tokens[i], tokens[i+1]], (255, 204, 204))
            i += 2; continue

        if tag.startswith('V') and form.endswith('지') and len(form) >= 2:
            root = form[:-1]
            jtext = "-여지다" if root.endswith('하') else ("-아지다" if is_yang_vowel(root) else "-어지다")
            
            if root.endswith('하') or root.endswith('해') or root.endswith('하여'):
                display_html.append(f"{root}- + " + PASSIVE_COLOR.format(text=f"{jtext}(비문)"))
                if check_mode in ['passive', 'all']:
                    error_msg += "🚨 '-하다'로 끝나는 말은 '-해지다(하여지다)' 대신 '-되다'를 쓰는 것이 자연스럽습니다. (예: 사용해지다 ❌ -> 사용되다 ⭕)\n\n"
            elif root.endswith('되') or root.endswith('되어') or root.endswith('돼'):
                found_passive = True
                display_html.append(f"{root}- + " + PASSIVE_COLOR.format(text=f"{jtext}(이중피동 주의)").replace("#ffcccc", "#ffe6cc"))
                if check_mode in ['passive', 'all']:
                    warning_msg += "💡 '-되다'에 '-어지다'가 또 붙은 '이중 피동'입니다. 고치는 것을 추천합니다! (일단 저장은 가능합니다)\n\n"
                mark_highlight([tokens[i]], (255, 230, 153))
            else:
                found_passive = True
                display_html.append(f"{root}- + " + PASSIVE_COLOR.format(text=f"{jtext}(피동)"))
                mark_highlight([tokens[i]], (255, 204, 204))
            bword = form + "다"
            base_forms.append({"word": bword, "valid": check_dict_api(bword), "type": "구조적피동"})
            i += 1; continue

        if tag == 'XSV' and form == '되':
            found_passive = True
            display_html.append(PASSIVE_COLOR.format(text="-되다(피동)"))
            if i > 0:
                bword = tokens[i - 1].form + "되다"
                base_forms.append({"word": bword, "valid": check_dict_api(bword), "type": "구조적피동"})
            mark_highlight([tokens[i]], (255, 204, 204))
            i += 1; continue

        # 💡 [핵심 패치] 이/히/리/기 검증 로직 완벽 수정 (퍼트리다 등 일반 단어 분리)
        if tag.startswith('V') and len(form) >= 2 and form[-1] in ['이', '히', '리', '기']:
            root, suffix = form[:-1], form[-1]
            bword = form + "다"
            
            if not TEACHER_API_KEY:
                display_html.append(f"{root}- + " + PASSIVE_COLOR.format(text=f"-{suffix}-(검증 불가)").replace("#ffcccc", "#e2e3e5"))
                if check_mode in ['passive', 'all']:
                    error_msg += f"⚠️ 표준국어대사전 API가 연동되지 않아 사동사 검증망이 작동하지 않습니다.\n\n"
                mark_highlight([tokens[i]], (226, 227, 229))
                base_forms.append({"word": bword, "valid": [], "type": "접사피동_검증불가"})
            else:
                plist = check_dict_api(bword)
                is_causative = '사동사' in plist
                is_passive = '피동사' in plist
                
                if is_causative and not is_passive:
                    display_html.append(f"{root}- + " + CAUSATIVE_COLOR.format(text=f"-{suffix}-(사동사)"))
                    mark_highlight([tokens[i]], (226, 227, 229)) 
                    base_forms.append({"word": bword, "valid": plist, "type": "접사_사동사"})
                elif is_causative and is_passive:
                    found_passive = True
                    display_html.append(f"{root}- + " + PASSIVE_COLOR.format(text=f"-{suffix}-(피동/사동 주의)").replace("#ffcccc", "#ffe6cc"))
                    if check_mode in ['passive', 'all']:
                        warning_msg += f"💡 '{bword}'는 문맥에 따라 피동/사동이 모두 가능합니다. 주체가 '당하는' 상황이 맞는지 확인해 보세요! 어려우면 선생님께 도움을 요청한 후 저장하세요.\n\n"
                    mark_highlight([tokens[i]], (255, 230, 153))
                    base_forms.append({"word": bword, "valid": plist, "type": "접사피동_둘다"})
                elif is_passive:
                    found_passive = True
                    display_html.append(f"{root}- + " + PASSIVE_COLOR.format(text=f"-{suffix}-(피동 접사)"))
                    mark_highlight([tokens[i]], (255, 204, 204))
                    base_forms.append({"word": bword, "valid": plist, "type": "접사피동_피동"})
                else:
                    # 💡 여기가 '퍼트리다', '내리다', '달리다' 등 사동사도 피동사도 아닌 일반 동사들이 걸러지는 곳입니다!
                    # 일반 동사이기 때문에 형광펜이나 경고 없이 그냥 조용히 글자만 출력합니다.
                    display_html.append(f"{form}-") 
                
            i += 1; continue

        is_indirect = False
        if tag == 'EC' and form in ['다고', '자고', '냐고']:
            is_indirect = True
            display_html.append(f"-{form[:-1]} + " + INDIRECT_COLOR.format(text="-고(간접 인용)"))
        elif tag == 'EC' and form == '라고' and i > 0 and tokens[i-1].tag == 'VCP': 
            is_indirect = True
            display_html.append(f"-라 + " + INDIRECT_COLOR.format(text="-고(간접 인용)"))
        elif tag == 'JKQ' and form == '고':
            is_indirect = True
            display_html.append(INDIRECT_COLOR.format(text="-고(간접 인용)"))

        if is_indirect:
            found_quote = True
            mark_highlight([tokens[i]], (212, 237, 218))
            i += 1; continue

        if form in ['"', '“', '”']: 
            display_html.append(DIRECT_COLOR.format(text=form))
            mark_highlight([tokens[i]], (204, 229, 255))
            i += 1; continue
            
        if tag == 'JKQ' and form in ['라고', '이라고', '하고']:
            found_quote = True
            display_html.append(DIRECT_COLOR.format(text=f"{form}(직접 인용)"))
            mark_highlight([tokens[i]], (204, 229, 255))
            i += 1; continue

        if tag.startswith('V'): display_html.append(f"{form}-")
        elif tag in ['EP', 'EC']: display_html.append(f"-{form}-")
        elif tag == 'EF': display_html.append(f"-{form}")
        else: display_html.append(form)
        i += 1

    if check_mode in ['passive', 'all']:
        if re.search(r'(되|돼)(어지|어져|어진|어질|어짐|어집|어지고|어지니|어지면)', text.replace(" ", "")):
            if "이중 피동" not in warning_msg:
                warning_msg += "💡 '-되다'에 '-어지다'가 또 붙은 '이중 피동'입니다. 문법상 틀린 표현이니 고치는 것을 추천합니다! (일단 저장은 가능합니다)\n\n"
                found_passive = True
                
        double_passive_patterns = ['먹혀지', '보여지', '쓰여지', '잊혀지', '읽혀지', '잡혀지', '닫혀지', '열려지', '팔려지', '풀려지', '들려지', '쫓겨지', '찢겨지', '안겨지', '담겨지', '끊겨지', '나뉘어지', '바뀌어지']
        for dp in double_passive_patterns:
            if dp in text.replace(" ", ""):
                if "이중 피동" not in warning_msg:
                    warning_msg += f"💡 '{dp}다'는 이미 사전에 등록된 피동사인데 '-어지다'가 불필요하게 또 붙은 '이중 피동'입니다. 문법상 틀린 표현이니 고치는 것을 추천합니다! (일단 저장은 가능합니다)\n\n"
                    found_passive = True
                break
                
        if re.search(r'(해지|하여지|해져|하여져|해진|하여진|해질|하여질|해짐|하여짐)', text.replace(" ", "")):
            if "자연스럽습니다" not in error_msg and "상태 변화" not in error_msg:
                error_msg += "🚨 '-하다'로 끝나는 동사는 '-해지다(하여지다)' 대신 '-되다'를 쓰는 것이 자연스럽습니다. (예: 사용해지다 ❌ -> 사용되다 ⭕)\n\n"

    if check_mode == 'passive' and not found_passive: error_msg += "🚨 올바른 피동 표현이 발견되지 않았습니다.\n\n"
    elif check_mode == 'quote' and not found_quote: error_msg += "🚨 인용 표현이 발견되지 않았습니다.\n\n"
    elif check_mode == 'all':
        if not found_passive: error_msg += "🚨 올바른 피동 표현 누락!\n\n"
        if not found_quote: error_msg += "🚨 인용 표현 누락!\n\n"

    is_passed = (len(error_msg.strip()) == 0)

    for b in base_forms:
        plist = b.get('valid', [])
        b_type = b.get('type', '')
        
        if b_type == '접사_사동사':
            b['is_correct'] = True 
            b['status_msg'] = "ℹ️ 사동사 (참고용)"
        elif b_type == '접사피동_둘다':
            b['is_correct'] = True
            b['status_msg'] = "⚠️ 피동/사동 주의 (문맥 확인)"
        elif b_type == '접사피동_피동':
            b['is_correct'] = True
            b['status_msg'] = "✅ 사전 확인 완료" if len(plist) > 0 else "💡 사전 미등재"
        elif b_type == '접사피동_검증불가':
            b['is_correct'] = False
            b['status_msg'] = "⚠️ API 미연결 (사동사 여부 검증 불가)"
        else:
            b['is_correct'] = True 
            if len(plist) > 0: b['status_msg'] = "✅ 사전 확인 완료"
            else: b['status_msg'] = "💡 사전 미등재 (구조적 피동 인정)"

    html_result = " + ".join(display_html)
    return is_passed, html_result, base_forms, error_msg, warning_msg, highlight_indices

def render_base_form_links(bases):
    if not bases: return ""
    links = []
    for b in bases:
        w, msg = b['word'], b['status_msg']
        color = "green" if "✅" in msg else ("#0066cc" if "ℹ️" in msg else ("#ff9900" if "⚠️" in msg or "💡" in msg else "red"))
        links.append(f"<a href='https://stdict.korean.go.kr/search/searchResult.do?pageSize=10&searchKeyword={urllib.parse.quote(w)}' target='_blank' style='text-decoration:none;'>🔍 <b>{w}</b></a> <span style='color:{color}; font-weight:bold;'>({msg})</span>")
    return "👉 [단어 사전에서 보기]: " + " | ".join(links)

# =========================================================================
# 6. 메인 레이아웃 UI 생성
# =========================================================================
STAGES = ["선택하세요", "[사용 전] 사용 가능 연령 확인하기", "[사용 전] 타인의 권리와 지적 재산권 존중", "[사용 중] 민감한 개인정보 입력 금지", "[사용 중] 할루시네이션 주의 및 팩트체크하기", "[사용 후] AI 생성 자료임을 명확히 표시", "[사용 후] 올바른 출처 표기법 준수"]

st.title("🤖 AI 윤리문 작성하기")
if not TEACHER_API_KEY:
    st.info("💡 관리자 콘솔(Secrets)에서 API 키를 등록해야 사동사 필터링이 작동합니다.")
st.markdown("---")

left_col, right_col = st.columns(2)

with left_col:
    st.header("👤 모둠원 개별 연습장")
    student_name = st.text_input("내 이름:", placeholder="예) 홍길동", key="left_name")
    left_stage = st.selectbox("우리 모둠 단계:", STAGES, key="left_stage")
    st.markdown("---")
    
    st.markdown("### 🎯 미션 1. 피동 표현 작성하기")
    st.caption("❓ 피동 표현을 사용하는 의도는 무엇인가요? (다중 선택 가능)")
    c1, c2 = st.columns(2)
    with c1:
        st.checkbox("행위 주체 숨기기", key="lp1")
        st.checkbox("당하는 대상 강조", key="lp2")
        st.checkbox("상대 배려", key="lp3")
    with c2:
        st.checkbox("책임 회피", key="lp4")
        st.checkbox("객관성 부여", key="lp5")
        
    st.text_area("피동 표현을 활용한 문장:", height=100, key="left_passive")
    
    btn_col1, btn_col2 = st.columns([3, 1])
    with btn_col1:
        check_p = st.button("📝 미션 1 피동 검사 맡기", key="btn_passive", use_container_width=True)
    with btn_col2:
        st.button("🔄 다시 하기", key="reset_p", on_click=clear_text, args=("left_passive",), use_container_width=True)
        
    if check_p:
        if not st.session_state.left_passive.strip(): st.warning("문장을 먼저 작성해주세요!")
        else:
            is_pass, html_str, bases, err, warn, _ = analyze_and_highlight(st.session_state.left_passive, 'passive')
            st.markdown(f"**[형태소 분석]** {html_str}", unsafe_allow_html=True)
            if bases: st.markdown(render_base_form_links(bases), unsafe_allow_html=True)
            if warn: st.warning(warn.strip(), icon="💡")
            if is_pass:
                p_intents = []
                if st.session_state.lp1: p_intents.append("행위 주체 숨기기")
                if st.session_state.lp2: p_intents.append("대상 강조")
                if st.session_state.lp3: p_intents.append("상대 배려")
                if st.session_state.lp4: p_intents.append("책임 회피")
                if st.session_state.lp5: p_intents.append("객관성 부여")
                
                if p_intents: st.success(f"✔️ 통과! '{', '.join(p_intents)}' 의도가 잘 담긴 피동 표현입니다.")
                else: st.success("✔️ 통과! 올바른 피동 표현입니다. (💡의도도 함께 체크해 보세요!)")
            else: st.error(err.strip(), icon="🚨")

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("### 🎯 미션 2. 인용 표현 작성하기")
    st.caption("❓ 인용 표현을 사용하는 의도는 무엇인가요? (다중 선택 가능)")
    st.checkbox("내용을 생생하게 전달하여 현장성 높이기", key="lq1")
    st.checkbox("권위 있는 견해를 인용하여 신뢰성/객관성 높이기", key="lq2")
    
    st.text_area("인용 표현을 활용한 문장:", height=100, key="left_quote")
    
    btn_col3, btn_col4 = st.columns([3, 1])
    with btn_col3:
        check_q = st.button("📝 미션 2 인용 검사 맡기", key="btn_quote", use_container_width=True)
    with btn_col4:
        st.button("🔄 다시 하기", key="reset_q", on_click=clear_text, args=("left_quote",), use_container_width=True)
        
    if check_q:
        if not st.session_state.left_quote.strip(): st.warning("문장을 먼저 작성해주세요!")
        else:
            is_pass, html_str, bases, err, warn, _ = analyze_and_highlight(st.session_state.left_quote, 'quote')
            st.markdown(f"**[형태소 분석]** {html_str}", unsafe_allow_html=True)
            if warn: st.warning(warn.strip(), icon="💡")
            if is_pass:
                q_intents = []
                if st.session_state.lq1: q_intents.append("생생함 전달")
                if st.session_state.lq2: q_intents.append("신뢰성/객관성 부여")
                
                if q_intents: st.success(f"✔️ 통과! '{', '.join(q_intents)}' 의도가 잘 드러나는 인용 표현입니다.")
                else: st.success("✔️ 통과! 올바른 인용 표현입니다. (💡의도도 함께 체크해 보세요!)")
            else: st.error(err.strip(), icon="🚨")

with right_col:
    st.header("👑 조장 최종 종합창")
    team_name = st.text_input("우리 모둠 이름:", placeholder="예) 000 모둠", key="right_team")
    
    st.markdown("#### ❓ 표현 사용 의도 종합 (최종 결과물에 기록됩니다)")
    rc1, rc2 = st.columns(2)
    with rc1:
        st.markdown("**[피동 표현 의도]**")
        rp1 = st.checkbox("행위 주체 숨기기", key="rp1")
        rp2 = st.checkbox("당하는 대상 강조", key="rp2")
        rp3 = st.checkbox("상대 배려", key="rp3")
        rp4 = st.checkbox("책임 회피", key="rp4")
        rp5 = st.checkbox("객관성 부여", key="rp5")
    with rc2:
        st.markdown("**[인용 표현 의도]**")
        rq1 = st.checkbox("현장성/생생함 전달", key="rq1")
        rq2 = st.checkbox("신뢰성/객관성 부여", key="rq2")
        
    st.text_area("모둠 최종 종합 홍보글:", height=270, key="right_content")
    
    btn_col5, btn_col6 = st.columns([3, 1])
    with btn_col5:
        check_all = st.button("🚀 최종 홍보글 점검 및 이미지 저장", key="right_btn", use_container_width=True)
    with btn_col6:
        st.button("🔄 다시 하기", key="reset_all", on_click=clear_text, args=("right_content",), use_container_width=True)
    
    if check_all:
        if not team_name.strip():
            st.error("🚨 모둠 이름을 반드시 입력해야 이미지를 저장할 수 있습니다!")
        elif not st.session_state.right_content.strip():
            st.warning("최종 종합 문구를 입력해 주세요!")
        else:
            is_pass, html_str, bases, err, warn, highlight_indices = analyze_and_highlight(st.session_state.right_content, 'all')
            
            st.markdown("#### 🏆 최종 모둠 결과서 점검")
            st.markdown(f"**[형태소 분석]** {html_str}", unsafe_allow_html=True)
            if bases: st.markdown(render_base_form_links(bases), unsafe_allow_html=True)
            
            if warn: st.warning(warn.strip(), icon="💡")
                
            if is_pass:
                st.balloons()
                st.success("🌟 완벽합니다! 피동과 인용이 모두 올바르게 적용된 훌륭한 윤리문입니다.")
                
                p_intents = []
                if rp1: p_intents.append("행위 주체 숨기기")
                if rp2: p_intents.append("대상 강조")
                if rp3: p_intents.append("상대 배려")
                if rp4: p_intents.append("책임 회피")
                if rp5: p_intents.append("객관성 부여")
                
                q_intents = []
                if rq1: q_intents.append("현장성/생생함 전달")
                if rq2: q_intents.append("신뢰성/객관성 부여")
                
                png_data = create_final_png(team_name, st.session_state.right_content, highlight_indices, p_intents, q_intents)
                safe_team = team_name.strip() if team_name.strip() else "모둠"
                
                st.download_button(
                    label="💾 갤러리에 저장하기 (PNG 이미지)", 
                    data=png_data, 
                    file_name=f"최종_홍보물_{safe_team}.png", 
                    mime="image/png",
                    type="primary"
                )
            else:
                st.error(err.strip(), icon="🚨")
