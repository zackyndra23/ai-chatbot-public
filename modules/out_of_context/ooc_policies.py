from __future__ import annotations
import os
import re
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class OOCPolicies:
    enabled: bool = os.getenv("OOC_AGENT_ENABLED", "on").strip().lower() in ("1","true","on","yes")
    mode: str = os.getenv("OOC_MODE", "keyword").strip().lower()  # keyword | hybrid | llm

    min_keyword_hits: int = int(os.getenv("OOC_MIN_KEYWORD_HITS", "1"))
    min_text_len: int = int(os.getenv("OOC_MIN_TEXT_LEN", "3"))
    min_confidence: float = float(os.getenv("OOC_MIN_CONFIDENCE", "0.70"))

    allowed_locales_csv: str = os.getenv("OOC_ALLOWED_LOCALES", "").strip()

    freelancer_url: str = os.getenv("OOC_FREELANCER_URL", "https://www.acmeservices.example.com/freelancer/").strip()
    # NOTE: partner_url previously defaulted to the freelancer page (bug).
    # Set OOC_PARTNER_URL in .env to override with the actual partnership
    # landing page for your region.
    partner_url: str = os.getenv("OOC_PARTNER_URL", "https://www.acmeservices.example.com/partner/").strip()

# =========================
# Keyword banks (punyamu sudah OK, cukup pastikan 10+ per bahasa)
# =========================
FREELANCE_KEYWORDS: tuple[str, ...] = (
    # EN (10)
    "freelance","freelancer","freelancing","part time","part-time","independent contractor",
    "contract worker","gig worker","project based","remote freelance",
    # ID (10)
    "freelance","freelancer","kerja lepas","pekerjaan lepas","pekerja lepas","kontrak lepas",
    "tenaga lepas","pekerjaan kontrak","kerja proyek","kerja paruh waktu",
    # MS (10)
    "freelance","freelancer","pekerja bebas","kerja bebas","kerja kontrak","kontrak bebas",
    "kerja sambilan","pekerja sambilan","kerja projek","kontrak projek",
    # TH (10)
    "ฟรีแลนซ์","งานฟรีแลนซ์","งานอิสระ","พนักงานอิสระ","ทำงานอิสระ","รับงานอิสระ",
    "งานสัญญาจ้าง","ทำงานตามสัญญา","งานชั่วคราว","งานนอกเวลา",
    # DE (10)
    "freelancer","freiberuflich","freiberufler","selbstständig","selbststaendig","freie mitarbeit",
    "projektarbeit","externer mitarbeiter","vertraglich","arbeit auf projektbasis",
    # FR (10)
    "freelance","travailleur indépendant","indépendant","auto entrepreneur","auto-entrepreneur",
    "prestataire indépendant","mission freelance","contrat freelance","travail en freelance","consultant indépendant",
    # RO (10)
    "freelancer","munca independenta","lucrator independent","lucrez independent","contractor independent",
    "munca pe proiect","munca contractuala","colaborator extern","prestator servicii","lucru pe contract",
    # IT (10)
    "freelance","lavoratore autonomo","libero professionista","collaboratore esterno","lavoro autonomo",
    "lavoro freelance","lavoro a progetto","contratto a progetto","consulente freelance","prestazione autonoma",
    # RU (10)
    "фриланс","фрилансер","удаленная работа","работа на фрилансе","внештатный сотрудник",
    "работа по контракту","проектная работа","самозанятый","частичная занятость","временная работа",
    # JA (10)
    "フリーランス","業務委託","個人事業主","業務委託契約","フリーランス契約",
    "外注","外部委託","請負業務","契約社員","プロジェクト契約",
    # ZH (10)
    "自由职业","自由职业者","自由工作者","外包","兼职","合同工","项目制","按项目工作","临时工作","独立承包商",
)

PARTNERSHIP_KEYWORDS: tuple[str, ...] = (
    # EN (10)
    "partner","partnership","business partner","strategic partner","collaboration","collaborate",
    "reseller","affiliate","referral partner","joint venture",
    # ID (10)
    "partner","mitra","kemitraan","kerja sama","kerjasama","kolaborasi","mitra bisnis","rekan bisnis","afiliasi","reseller",
    # MS (10)
    "rakan kongsi","perkongsian","kerjasama","mitra","rakan niaga","kerjasama perniagaan","kolaborasi","program rakan","reseller","affiliate",
    # TH (10)
    "พาร์ทเนอร์","พันธมิตร","คู่ค้า","ความร่วมมือ","ความเป็นพันธมิตร","ร่วมมือทางธุรกิจ","พันธมิตรทางธุรกิจ","ตัวแทนจำหน่าย","พันธมิตรเชิงกลยุทธ์","โครงการความร่วมมือ",
    # DE (10)
    "partner","partnerschaft","geschäftspartner","kooperation","zusammenarbeit","strategischer partner","vertriebspartner","reseller","affiliate partner","joint venture",
    # FR (10)
    "partenaire","partenariat","collaboration","coopération","partenaire commercial","partenaire stratégique","programme partenaire","revendeur","affiliation","joint venture",
    # RO (10)
    "partener","parteneriat","colaborare","partener de afaceri","partener comercial","cooperare","partener strategic","program de parteneriat","revanzator","afiliere",
    # IT (10)
    "partner","partnership","collaborazione","partner commerciale","partner strategico","cooperazione","programma partner","rivenditore","affiliazione","joint venture",
    # RU (10)
    "партнер","партнерство","деловой партнер","сотрудничество","коммерческое партнерство","стратегический партнер","партнерская программа","дистрибьютор","аффилиат","совместное предприятие",
    # JA (10)
    "パートナー","提携","協業","ビジネスパートナー","業務提携","戦略的パートナー","販売代理店","パートナープログラム","アライアンス","共同事業",
    # ZH (10)
    "合作伙伴","伙伴关系","商业合作","战略合作","业务合作","合作关系","联合合作","代理合作","分销合作","联盟",
)

# =========================
# Intent-phrase banks (STRICT): explicit "want to be / become / join as ..."
# phrases. Used for MID-SA-FLOW detection to avoid false positives like
# "kerja sama untuk pelaporan anonim" (cooperation FOR a service, not
# partnership intent). Single-keyword matches no longer trigger mid-flow —
# only a full intent phrase does.
# =========================
FREELANCE_INTENT_PHRASES: tuple[str, ...] = (
    # EN — explicit intent
    "become a freelancer", "be a freelancer", "join as freelancer",
    "join as a freelancer", "apply as freelancer", "apply as a freelancer",
    "work as freelance", "want to be freelance", "want to freelance",
    "hire me as freelancer", "register as freelancer",
    # EN — 2026-05-19 expansion per Intent_Signal_Examples
    "freelance work for acme services", "freelance work for",
    "do freelance work", "independent investigator",
    "i'm an independent investigator", "as a contractor",
    "as a freelancer", "as freelancer", "as freelance",
    "work as a contractor", "work as a freelancer",
    "field-research experience", "field research experience",
    "join your pool", "join your investigator pool",
    "i have field experience",
    # ID — explicit intent (legacy)
    "jadi freelancer", "menjadi freelancer", "gabung sebagai freelancer",
    "daftar freelancer", "daftar sebagai freelancer", "lamar freelancer",
    "lamar sebagai freelancer", "jadi pekerja lepas", "menjadi pekerja lepas",
    "daftar pekerja lepas", "gabung pekerja lepas",
    # ID — 2026-05-19 expansion
    "kerja freelance untuk acme services", "investigator independen",
    "investigator lepas", "saya investigator independen",
    "sebagai kontraktor", "gabung sebagai kontraktor",
    "punya pengalaman lapangan", "pengalaman riset lapangan",
    "ikut pool freelancer",
    # MS
    "jadi pekerja bebas", "menjadi pekerja bebas", "sertai sebagai freelancer",
    "mohon sebagai freelancer", "daftar pekerja bebas",
    # FR
    "devenir freelance", "devenir freelancer", "travailler en freelance",
    "postuler comme freelance",
    # DE
    "als freelancer arbeiten", "freelancer werden", "freiberuflich arbeiten",
    # IT
    "diventare freelance", "lavorare come freelance",
    # ES
    "ser freelancer", "trabajar como freelance",
    # PT
    "ser freelancer", "trabalhar como freelance",
    # TH
    "สมัครฟรีแลนซ์", "เป็นฟรีแลนซ์",
    # RU
    "стать фрилансером", "работать фрилансером",
    # JA
    "フリーランスになる", "フリーランスとして",
    # ZH
    "成为自由职业", "做自由职业者", "当自由职业",
)

PARTNERSHIP_INTENT_PHRASES: tuple[str, ...] = (
    # EN — explicit intent (legacy)
    "become a partner", "be a partner", "become partners", "be partners",
    "join as partner", "join as a partner", "partner with acme services",
    "partner with you", "reseller program", "affiliate program",
    "partnership program", "referral program", "become reseller",
    "become an affiliate", "business partnership", "strategic partnership",
    # EN — 2026-05-19 expansion per Intent_Signal_Examples
    "propose a partnership", "proposing a partnership",
    "would like to propose a partnership", "we'd like to propose",
    "channel partner", "channel partner program",
    "vendor partnership", "white-label", "white label",
    "strategic alliance", "co-marketing", "co marketing",
    "referral agreement", "reseller agreement", "reseller / referral",
    "referral / reseller", "joint marketing", "form a partnership",
    "set up a partnership",
    # ID — explicit intent (legacy)
    "jadi mitra", "menjadi mitra", "jadi partner", "menjadi partner",
    "gabung sebagai mitra", "bergabung sebagai mitra", "mau jadi mitra",
    "ingin jadi mitra", "ingin menjadi mitra", "program mitra",
    "program kemitraan", "program reseller", "program afiliasi",
    "mitra bisnis", "mitra strategis",
    # ID — 2026-05-19 expansion
    "tawarkan kemitraan", "menawarkan kemitraan",
    "mengajukan kemitraan", "ingin mengajukan kemitraan",
    "kemitraan strategis", "aliansi strategis",
    "channel partner", "mitra channel", "kemitraan channel",
    "kemitraan vendor", "white label", "white-label",
    "kerjasama pemasaran", "co-marketing",
    "perjanjian referral", "perjanjian reseller",
    # MS
    "jadi rakan kongsi", "menjadi rakan kongsi", "program rakan",
    "program rakan niaga", "jadi pengedar", "program pengedar",
    # FR
    "devenir partenaire", "être partenaire", "programme partenaire",
    "programme de revendeur", "programme d'affiliation",
    # DE
    "partner werden", "geschäftspartner werden", "partnerprogramm",
    "vertriebspartner werden",
    # IT
    "diventare partner", "programma partner", "programma affiliati",
    # ES
    "ser socio", "ser partner", "programa de socios", "programa partner",
    "programa de afiliados",
    # PT
    "ser parceiro", "programa de parceiros", "programa de afiliados",
    # TH
    "เป็นพันธมิตร", "สมัครพันธมิตร", "โปรแกรมพันธมิตร",
    # RU
    "стать партнером", "стать партнёром", "партнерская программа",
    # JA
    "パートナーになる", "パートナー募集", "パートナー申込",
    # ZH
    "成为合作伙伴", "成为伙伴", "合作伙伴计划", "代理商计划",
)


# =========================
# Reply templates per language
# =========================
REPLIES = {
    "freelance": {
        "en": "Thank you for your interest to join Acme Services as a freelancer. Please visit this link ({url}) for detailed information.",
        "id": "Terima kasih atas ketertarikan Anda untuk bergabung sebagai freelancer di Acme Services. Silakan kunjungi tautan ini ({url}) untuk informasi lebih lanjut.",
        "ms": "Terima kasih atas minat anda untuk menyertai Acme Services sebagai freelancer. Sila lawati pautan ini ({url}) untuk maklumat lanjut.",
        "th": "ขอบคุณที่สนใจเข้าร่วม Acme Services ในฐานะฟรีแลนซ์ โปรดเยี่ยมชมลิงก์นี้ ({url}) สำหรับข้อมูลเพิ่มเติม",
        "de": "Vielen Dank für Ihr Interesse, als Freelancer bei Acme Services mitzuarbeiten. Bitte besuchen Sie diesen Link ({url}) für weitere Informationen.",
        "fr": "Merci pour votre intérêt à rejoindre Acme Services en tant que freelance. Veuillez consulter ce lien ({url}) pour plus d’informations.",
        "ro": "Vă mulțumim pentru interesul de a vă alătura Acme Services ca freelancer. Vă rugăm să accesați acest link ({url}) pentru mai multe informații.",
        "it": "Grazie per il tuo interesse a collaborare con Acme Services come freelance. Visita questo link ({url}) per maggiori informazioni.",
        "ru": "Спасибо за интерес к сотрудничеству с Acme Services в качестве фрилансера. Пожалуйста, перейдите по ссылке ({url}) для подробной информации.",
        "ja": "Integrityでフリーランスとして参加をご検討いただきありがとうございます。詳細は以下のリンク（{url}）をご確認ください。",
        "zh": "感谢您有兴趣以自由职业者身份加入Integrity。请访问此链接（{url}）了解更多信息。",
    },
    "partnership": {
        "en": "Thank you for your interest to become Acme Services's partner. Please visit this link ({url}) for detailed information.",
        "id": "Terima kasih atas ketertarikan Anda untuk menjadi mitra Acme Services. Silakan kunjungi tautan ini ({url}) untuk informasi lebih lanjut.",
        "ms": "Terima kasih atas minat anda untuk menjadi rakan kongsi Acme Services. Sila lawati pautan ini ({url}) untuk maklumat lanjut.",
        "th": "ขอบคุณที่สนใจเป็นพันธมิตรกับ Acme Services โปรดเยี่ยมชมลิงก์นี้ ({url}) สำหรับข้อมูลเพิ่มเติม",
        "de": "Vielen Dank für Ihr Interesse an einer Partnerschaft mit Acme Services. Bitte besuchen Sie diesen Link ({url}) für weitere Informationen.",
        "fr": "Merci pour votre intérêt à devenir partenaire d’Acme Services. Veuillez consulter ce lien ({url}) pour plus d’informations.",
        "ro": "Vă mulțumim pentru interesul de a deveni partener Acme Services. Vă rugăm să accesați acest link ({url}) pentru mai multe informații.",
        "it": "Grazie per il tuo interesse a diventare partner di Acme Services. Visita questo link ({url}) per maggiori informazioni.",
        "ru": "Спасибо за интерес к партнерству с Acme Services. Пожалуйста, перейдите по ссылке ({url}) для подробной информации.",
        "ja": "Integrityとのパートナー提携にご関心をお寄せいただきありがとうございます。詳細は以下のリンク（{url}）をご確認ください。",
        "zh": "感谢您有兴趣成为Integrity的合作伙伴。请访问此链接（{url}）了解更多信息。",
    },
}

def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def pick_language_bucket(language_code: str | None) -> str:
    lc = (language_code or "").strip().lower()
    if not lc:
        return "en"
    # prefix mapping (id-ID -> id, zh-CN -> zh)
    if lc.startswith("id"): return "id"
    if lc.startswith("ms"): return "ms"
    if lc.startswith("th"): return "th"
    if lc.startswith("de"): return "de"
    if lc.startswith("fr"): return "fr"
    if lc.startswith("ro"): return "ro"
    if lc.startswith("it"): return "it"
    if lc.startswith("ru"): return "ru"
    if lc.startswith("ja"): return "ja"
    if lc.startswith("zh"): return "zh"
    return "en"

def build_reply(label: str, *, language_code: str | None, freelancer_url: str, partner_url: str) -> str:
    lang = pick_language_bucket(language_code)
    if label == "freelance":
        tmpl = REPLIES["freelance"].get(lang) or REPLIES["freelance"]["en"]
        return tmpl.format(url=freelancer_url)
    if label == "partnership":
        tmpl = REPLIES["partnership"].get(lang) or REPLIES["partnership"]["en"]
        return tmpl.format(url=partner_url)
    return ""

def is_locale_allowed(p: OOCPolicies, language_code: str | None) -> bool:
    csv = (p.allowed_locales_csv or "").strip()
    if not csv:
        return True
    allowed = [x.strip().lower() for x in csv.split(",") if x.strip()]
    if not allowed:
        return True
    lc = (language_code or "").strip().lower()
    if not lc:
        return False
    return any(lc == a or lc.startswith(a + "-") or lc.startswith(a) for a in allowed)

def keyword_hits(text: str, keywords: Iterable[str]) -> int:
    t = _norm(text)
    hits = 0
    for kw in keywords:
        k = _norm(kw)
        if k and k in t:
            hits += 1
    return hits


def classify_intent_phrase_strict(text: str) -> str:
    """
    Strict intent-phrase detection for MID-SA-FLOW use.

    Returns "freelance", "partnership", or "none". Only fires when the user
    text contains an explicit "want to be / become / join as ..." phrase —
    NOT just a single partnership/cooperation keyword. This prevents
    false positives like "kerja sama untuk pelaporan anonim" (which contains
    the keyword "kerja sama" but not the phrase "jadi mitra"/"menjadi mitra").
    """
    t = _norm(text)
    if not t:
        return "none"
    for p in FREELANCE_INTENT_PHRASES:
        if _norm(p) and _norm(p) in t:
            return "freelance"
    for p in PARTNERSHIP_INTENT_PHRASES:
        if _norm(p) and _norm(p) in t:
            return "partnership"
    return "none"

def cheap_precheck(text: str, p: OOCPolicies) -> bool:
    t = (text or "").strip()
    if not p.enabled:
        return False
    if len(t) < p.min_text_len:
        return False
    fh = keyword_hits(t, FREELANCE_KEYWORDS)
    ph = keyword_hits(t, PARTNERSHIP_KEYWORDS)
    return (fh + ph) >= p.min_keyword_hits


# =========================================================================
# Stage 0 OOC additions (2026-05-13) — 11 new category keyword banks
# See docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §1.2.
#
# Structure: dict[lang_code, list[str]] keyword phrases (lowercase).
# Phase 2a scope: en + id only. Other 15 langs land in Phase 2b/2c/2d.
# Romanian (ro) intentionally NOT present per spec Q#1 default-drop.
# =========================================================================

MYSTERY_SHOPPER_APPLY_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "be a mystery shopper", "become a mystery shopper",
        "join as mystery shopper", "join as a mystery shopper",
        "apply as mystery shopper", "apply as a mystery shopper",
        "mystery shopper application", "mystery shopper pool",
        "want to be a shopper",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "want to be a mystery shopper", "sign up as a mystery shopper",
        "sign up as a shopper", "sign up as shopper",
        "apply to be a field shopper", "apply to be a shopper",
        "field shopper", "mystery shopper job",
        "shopper job", "secret shopper job",
        "how do i sign up as a shopper", "how to be a shopper",
    ],
    "id": [
        # legacy
        "jadi mystery shopper", "menjadi mystery shopper",
        "gabung mystery shopper", "gabung sebagai mystery shopper",
        "daftar mystery shopper", "daftar sebagai mystery shopper",
        "lamar mystery shopper", "ikut mystery shopper",
        # 2026-05-19 expansion
        "daftar jadi shopper", "daftar shopper",
        "ingin jadi mystery shopper", "mau jadi shopper",
        "pekerjaan mystery shopper", "kerja mystery shopper",
        "lowongan mystery shopper", "shopper lapangan",
    ],
}

CAREERS_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "career", "careers", "job opening", "job openings",
        "full-time position", "internship", "intern position",
        "send my cv", "send my resume", "career inquiry",
        "looking for a job", "hiring",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "are you hiring", "do you have openings",
        "apply for a job", "want to apply for a job",
        "openings for analysts", "any openings",
        "career opportunity", "career opportunities",
        "internship opportunities", "internships available",
        "do you have internships", "vacancy", "vacancies",
    ],
    "id": [
        # legacy
        "karir", "karier", "lowongan", "lowongan kerja",
        "magang", "internship", "kirim cv", "kirim resume",
        "lamaran kerja", "rekrutmen",
        # 2026-05-19 expansion
        "apakah ada lowongan", "ada lowongan",
        "lamar pekerjaan", "kirim lamaran",
        "kesempatan karir", "peluang karir",
        "ada magang", "buka lowongan", "kirim cv saya",
    ],
}

ADJACENT_SERVICE_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "tax consult", "tax consulting", "tax advisory",
        "audit firm", "external audit", "accounting service",
        "accounting firm", "bookkeeping", "legal counsel",
        "law firm", "legal advice", "do you offer",
        "do you provide", "do you do", "do you handle",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "tax audit", "tax audits",
        "lawyering", "legal services",
        "penetration testing", "pen testing", "pentest",
        "cybersecurity audit", "cybersecurity audits",
        "cyber security audit", "security audit",
        "credit scoring", "credit bureau",
        "credit scoring as a bureau",
        "private investigator", "private investigation",
        "personal investigator", "personal investigation",
        "divorce investigation", "custody investigation",
        "investigator for divorce", "investigator for custody",
        "investigation for personal matters",
    ],
    "id": [
        # legacy
        "konsultasi pajak", "konsultan pajak",
        "kantor audit", "audit eksternal", "jasa akuntansi",
        "kantor akuntan", "pembukuan", "konsultan hukum",
        "kantor hukum", "apakah anda menyediakan",
        "apakah anda menawarkan", "layanan hukum",
        # 2026-05-19 expansion
        "audit pajak", "jasa hukum",
        "uji penetrasi", "penetration testing",
        "audit keamanan siber", "audit keamanan",
        "skoring kredit", "biro kredit",
        "detektif swasta", "penyelidik swasta",
        "investigasi pribadi", "investigasi perceraian",
        "investigasi hak asuh", "investigasi keluarga",
    ],
}

ADJACENT_ISO_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "iso certification", "iso 37001", "iso 27001", "iso 9001",
        "iso audit", "iso accreditation", "iso compliance",
        "certify iso", "get iso",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "certify us for iso", "iso certification body",
        "want iso certification", "want iso 9001",
        "want iso 27001", "want iso 37001",
        "iso certified", "get iso certified",
        "obtain iso", "iso 14001", "iso body",
    ],
    "id": [
        # legacy
        "sertifikasi iso", "iso 37001", "iso 27001", "iso 9001",
        "audit iso", "akreditasi iso", "kepatuhan iso",
        "tersertifikasi iso",
        # 2026-05-19 expansion
        "lembaga sertifikasi iso", "badan sertifikasi iso",
        "mau sertifikasi iso", "ingin sertifikasi iso",
        "dapat sertifikat iso",
    ],
}

PRESS_MEDIA_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "press inquiry", "media inquiry", "media outlet",
        "interview request", "journalist", "press release",
        "media contact", "news outlet", "magazine",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "working on a story", "writing a story",
        "i'm a journalist", "i am a journalist",
        "interview your ceo", "interview your founder",
        "comment for an article", "comment on the",
        "quote for our story", "quote for an article",
        "press contact", "media request",
        "news article", "news story",
    ],
    "id": [
        # legacy
        "pertanyaan pers", "pertanyaan media", "wawancara",
        "permintaan wawancara", "jurnalis", "siaran pers",
        "kontak media", "outlet berita",
        # 2026-05-19 expansion
        "sedang menulis berita", "sedang membuat berita",
        "wawancara ceo", "wawancara dengan ceo",
        "komentar untuk artikel", "kutipan untuk artikel",
        "permintaan media", "konferensi pers",
    ],
}

VENDOR_SUPPLIER_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "vendor", "supplier", "we provide", "our service offering",
        "our product", "introduce our company", "we are a vendor",
        "vendor introduction", "wholesale", "procurement opportunity",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "sell you", "sell you software", "sell software",
        "want to sell", "selling to acme services",
        "office services", "we offer office",
        "vendor onboarding", "we are vendors",
        "vendor for", "be your vendor", "be your supplier",
        "procurement inquiry", "procurement enquiry",
    ],
    "id": [
        # legacy
        "vendor", "pemasok", "kami menyediakan", "produk kami",
        "perusahaan kami", "perkenalan vendor",
        "peluang pengadaan", "grosir",
        # 2026-05-19 expansion
        "jual software", "menjual software",
        "ingin menjual", "tawarkan software",
        "onboarding vendor", "kami vendor",
        "pengadaan", "permintaan pengadaan",
        "layanan kantor",
    ],
}

COMPLAINT_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "complain", "complaint", "dissatisfied", "unhappy with",
        "poor service", "bad experience", "unacceptable",
        "disappointed with", "frustrated with",
        "want to report a problem", "issue with your service",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "unhappy with the investigation",
        "unhappy with the report", "unhappy with your report",
        "your team didn't deliver", "team did not deliver",
        "didn't deliver", "did not deliver",
        "file a complaint", "want to file a complaint",
        "this is a service issue", "service issue",
        "service quality", "service-quality concern",
        "report a problem", "raise a complaint",
    ],
    "id": [
        # legacy
        "mengeluh", "keluhan", "tidak puas", "kecewa",
        "layanan buruk", "pengalaman buruk", "tidak dapat diterima",
        "kecewa dengan", "frustrasi dengan",
        "masalah dengan layanan",
        # 2026-05-19 expansion
        "tidak puas dengan laporan", "kecewa dengan laporan",
        "tim tidak mengirim", "tidak menyelesaikan",
        "ajukan keluhan", "ingin mengajukan keluhan",
        "masalah kualitas layanan", "kualitas layanan",
        "lapor masalah", "lapor keluhan",
    ],
}

PERSONAL_ADVICE_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "personal advice", "my situation", "what should i do",
        "give me advice", "should i hire a lawyer",
        "personal legal", "my divorce", "my marriage",
        "my health", "my finances",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "legal advice on my contract", "advice on my contract",
        "my contract", "my landlord", "landlord is",
        "medical advice", "medical question",
        "health question", "health advice",
        "investment advice", "stock advice", "financial advice",
        "personal divorce", "custody help", "custody advice",
        "how do i sue", "how to sue", "sue someone",
        "sue my", "advice on my",
        "my taxes", "tax advice for me",
    ],
    "id": [
        # legacy
        "nasihat pribadi", "situasi saya", "apa yang harus saya lakukan",
        "perlu nasihat", "saran pribadi",
        "perceraian saya", "kesehatan saya", "keuangan saya",
        # 2026-05-19 expansion
        "saran tentang kontrak saya", "kontrak saya",
        "tuan tanah saya", "pemilik kos saya",
        "saran medis", "pertanyaan medis",
        "saran kesehatan", "saran investasi",
        "saran saham", "saran keuangan pribadi",
        "perceraian pribadi", "bantuan hak asuh",
        "bagaimana cara menggugat", "cara menggugat",
        "menggugat seseorang", "pajak pribadi saya",
    ],
}

CHITCHAT_KEYWORDS: dict[str, list[str]] = {
    "en": [
        # legacy
        "how are you", "tell me a joke", "what's your name",
        "are you human", "are you an ai", "are you real",
        "good morning bot", "thanks bot", "lol",
        # 2026-05-19 expansion per Intent_Signal_Examples
        "what's the weather", "whats the weather", "the weather",
        "weather today",
        "write me a poem", "write a poem",
        "tell me a poem", "compose a poem",
        "my homework", "do my homework",
        "homework help", "help with homework",
        "your opinion", "what do you think about",
        "what do you think of", "what do you think",
        "tell me a story", "sing me a song",
    ],
    "id": [
        # legacy
        "apa kabar", "ceritakan lelucon", "siapa namamu",
        "anda manusia", "anda ai", "anda robot",
        "selamat pagi bot", "terima kasih bot",
        # 2026-05-19 expansion
        "cuaca hari ini", "bagaimana cuaca", "cuaca di",
        "buatkan puisi", "tulis puisi", "tulis sajak",
        "kerjakan pr saya", "bantu pr saya", "pr saya",
        "menurutmu", "menurut anda",
        "ceritakan dongeng", "nyanyikan lagu",
    ],
}

# Strict-keyword categories (deterministic). Evaluated before LLM classifier.
KEYWORD_CATEGORIES_BY_LANG: list[tuple[str, dict[str, list[str]]]] = [
    ("OOC-MYSTERY-SHOPPER-APPLY", MYSTERY_SHOPPER_APPLY_KEYWORDS),
    ("OOC-CAREERS", CAREERS_KEYWORDS),
    ("OOC-PRESS-MEDIA", PRESS_MEDIA_KEYWORDS),
    ("OOC-VENDOR-SUPPLIER", VENDOR_SUPPLIER_KEYWORDS),
    ("OOC-COMPLAINT", COMPLAINT_KEYWORDS),
]

# Fuzzy categories — keyword match is a hint but LLM resolves in hybrid mode.
# In keyword-only mode, these still fire on keyword match (lower confidence).
# Order: most specific → least specific (first match wins). PERSONAL-ADVICE
# and ADJACENT-ISO check before ADJACENT-SERVICE because the latter's generic
# keywords (e.g. "legal advice", "do you offer") would otherwise swallow more
# specific personal/ISO queries.
FUZZY_CATEGORIES_BY_LANG: list[tuple[str, dict[str, list[str]]]] = [
    ("OOC-ADJACENT-ISO", ADJACENT_ISO_KEYWORDS),
    ("OOC-PERSONAL-ADVICE", PERSONAL_ADVICE_KEYWORDS),
    ("OOC-CHITCHAT", CHITCHAT_KEYWORDS),
    ("OOC-ADJACENT-SERVICE", ADJACENT_SERVICE_KEYWORDS),
]


# =========================================================================
# In-scope protection (Constraint #4)
#
# When user message arrives during active_service flow, classifier checks
# IN_SCOPE_SERVICE_TERMS[service_id][lang] BEFORE firing OOC. If text matches
# an in-scope term, classifier returns yes=False ("in_scope_protection").
#
# Bank intentionally narrow — only unambiguous in-scope terminology.
# Expanding bank reduces OOC false-positives but risks letting OOC through;
# tune based on production query_recording analysis.
# =========================================================================

IN_SCOPE_SERVICE_TERMS: dict[str, dict[str, list[str]]] = {
    "wbs": {
        "en": [
            "case handler", "case manager", "whistleblower",
            "reporting channel", "investigation timeline",
            "anonymity", "anonymous reporting", "retaliation",
            "wbs platform", "wbs implementation", "whistleblowing hotline",
        ],
        "id": [
            "penanggung jawab kasus", "case handler",
            "pelapor", "saluran pelaporan", "investigasi",
            "anonim", "pelaporan anonim", "pembalasan",
            "sistem whistleblowing", "platform wbs",
        ],
    },
    "ebs": {
        "en": [
            "background check", "background screening",
            "criminal record", "education verify", "education verification",
            "previous employer", "screening report",
            "reference check", "credential verify",
        ],
        "id": [
            "pemeriksaan latar belakang", "verifikasi latar belakang",
            "catatan kriminal", "verifikasi pendidikan",
            "mantan atasan", "laporan screening",
            "pemeriksaan referensi",
        ],
    },
    "due_diligence": {
        "en": [
            "entity verify", "entity verification",
            "beneficial owner", "ubo", "ultimate beneficial owner",
            "kyc", "compliance check", "due diligence report",
            "third-party risk",
        ],
        "id": [
            "verifikasi entitas", "pemilik manfaat",
            "pemeriksaan kepatuhan", "laporan due diligence",
            "risiko pihak ketiga",
        ],
    },
    "mystery_shopping": {
        "en": [
            "mystery shopper engagement", "shopper deployment",
            "store visit", "mystery audit",
            "secret shopper program", "evaluation report",
            "shopper coverage", "outlet coverage",
        ],
        "id": [
            "kunjungan toko", "audit mystery",
            "program mystery shopper", "laporan evaluasi",
            "cakupan outlet",
        ],
    },
    "compliance_audit": {
        "en": [
            "fraud investigation", "internal fraud",
            "embezzlement", "asset misappropriation",
            "fraud scheme", "investigation report",
            "evidence gathering", "interview subjects",
        ],
        "id": [
            "investigasi fraud", "fraud internal",
            "penggelapan", "penyalahgunaan aset",
            "skema fraud", "laporan investigasi",
            "pengumpulan bukti",
        ],
    },
    "claim_review": {
        "en": [
            "claim verification", "claim investigation",
            "policy holder", "insurance fraud",
            "claim review", "claim adjuster",
            "claim assessment", "fraudulent claim",
            "claim documentation",
        ],
        "id": [
            "verifikasi klaim", "investigasi klaim",
            "pemegang polis", "fraud asuransi",
            "tinjauan klaim", "klaim palsu",
            "penilaian klaim", "dokumentasi klaim",
        ],
    },
    "asset_verification": {
        "en": [
            "asset recovery", "trace assets", "hidden assets",
            "beneficial ownership", "financial investigation",
            "judgment enforcement", "debt recovery",
            "asset disclosure", "offshore assets",
        ],
        "id": [
            "pemulihan aset", "pelacakan aset", "aset tersembunyi",
            "pemilik manfaat", "investigasi finansial",
            "penegakan putusan", "pemulihan utang",
            "aset luar negeri",
        ],
    },
    "contact_verification": {
        "en": [
            "locate person", "locate debtor", "missing person",
            "contact information", "residence verification",
            "employment verification", "public records search",
            "subject location",
        ],
        "id": [
            "melacak orang", "melacak debitur", "orang hilang",
            "informasi kontak", "verifikasi tempat tinggal",
            "verifikasi pekerjaan", "pencarian catatan publik",
            "lokasi subjek",
        ],
    },
    # =======================================================================
    # COVERAGE NOTE (per spec §Constraint #4 + Task 7 Phase 2 review)
    #
    # 8 of 15 service lines covered above. The remaining 7 services rely on
    # the LLM classifier confidence threshold (OOC_LLM_CONFIDENCE_FLOOR=0.6)
    # for in-scope protection rather than per-service term banks:
    #
    #   kyc                            (Prevention)
    #   abms_elearning                 (Prevention)
    #   market_research                  (Detection)
    #   non_use_investigation          (Brand Protection)
    #   anti_counterfeit_investigation (Brand Protection)
    #   parallel_trading_investigation (Brand Protection)
    #   trademark_investigation        (Brand Protection)
    #
    # Rationale: graduated rollout per Phase 0 MVP scope. The 8 covered
    # services prioritize: (a) all 4 OOC_HIGH_STAKES_SERVICES (high consequence
    # of false-positive OOC on a P4-routing flow), plus (b) 4 highest-traffic
    # Prevention/Detection services that drive most qualification volume.
    #
    # Expansion criteria: add a service's bank when production query_recording
    # shows ≥1% false-positive OOC rate during that service's flow. Per spec §6.1
    # process gate, this is a Phase 1 empirical-tuning activity, not pre-deploy
    # work.
    # =======================================================================
}