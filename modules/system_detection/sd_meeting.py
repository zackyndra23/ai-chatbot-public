from __future__ import annotations
from typing import Optional
import re

from .meeting_arrangement.ma_policies import detect_meeting_intent


def is_meeting_request(text: str, language_code: Optional[str]) -> bool:
    """
    Heuristik ringan untuk mendeteksi permintaan meeting / appointment
    di berbagai bahasa tanpa LLM tambahan.

    - Utama: pakai detect_meeting_intent() yang sudah ada.
    - Tambahan: keyword multi-bahasa sebagai backup.
    """
    if not text:
        return False

    t = text.lower()
    lang = (language_code or "").lower()

    # 1) Pakai detector yang sudah ada (ma_policies)
    try:
        is_meet, _meta = detect_meeting_intent(text)
        if is_meet:
            return True
    except Exception:
        # kalau detector crash jangan matikan flow
        pass

    # 2) Keyword generik lintas bahasa
    generic_kw = [
        "meeting", "appointment", "schedule a call", "schedule a meeting",
        "book a call", "video call", "zoom call", "teams call",
        "call your team", "meet your team",
    ]
    if any(k in t for k in generic_kw):
        return True

    # 3) Keyword spesifik per bahasa (11 bahasa)
    lang_kw: list[str] = []

    if lang.startswith("id"):
        lang_kw = [
            "janji temu", "janjian", "ketemu tim", "ketemu dengan tim",
            "pertemuan", "meeting dengan tim", "jadwalkan meeting",
            "temu janji", "bertemu tim integrity",
        ]
    elif lang.startswith("ms"):
        lang_kw = [
            "temu janji", "janji temu", "bertemu pasukan", "pertemuan",
            "meeting dengan pasukan", "jadualkan meeting",
        ]
    elif lang.startswith("fr"):
        lang_kw = [
            "rendez-vous", "prendre rendez vous", "prise de rendez vous",
            "réunion", "rencontre avec votre équipe",
        ]
    elif lang.startswith("de"):
        lang_kw = [
            "termin", "besprechung", "einen termin vereinbaren",
            "treffen mit ihrem team", "meeting anfragen",
        ]
    elif lang.startswith("it"):
        lang_kw = [
            "appuntamento", "fissare un incontro", "riunione",
            "incontrare il vostro team",
        ]
    elif lang.startswith("rm"):
        lang_kw = [
            "appuntament", "inscunter", "inscuntrar vies team",
        ]
    elif lang.startswith("ru"):
        lang_kw = [
            "встречу", "встреча", "созвон", "созвониться",
            "назначить звонок", "назначить встречу", "встретиться с вашей командой",
        ]
    elif lang.startswith("th"):
        lang_kw = [
            "นัดหมาย", "ขอนัด", "ขอประชุม", "อยากคุยกับทีม",
            "นัดประชุมกับทีมของคุณ",
        ]
    elif lang.startswith("es"):
        lang_kw = [
            "reunión", "reunion", "programar una llamada",
            "agendar una reunión", "reunirme con su equipo",
        ]
    elif lang.startswith("pt"):
        lang_kw = [
            "reunião", "reuniao", "marcar uma reunião",
            "agendar uma chamada", "falar com a sua equipa", "falar com sua equipe",
        ]
    elif lang.startswith("en"):
        lang_kw = [
            "set up a meeting", "arrange a meeting", "set a meeting",
            "book a meeting", "talk with your team",
        ]

    if any(k in t for k in lang_kw):
        return True

    # 4) Fallback combo: kata "meet/meeting/appointment" + "team/sales"
    if re.search(r"\b(meet(?:ing)?|appointment|rendez[- ]vous|termin|reunion|reuni[oã]o)\b", t) and \
       re.search(r"\b(team|sales|your team|tim anda|tim kamu)\b", t):
        return True

    return False


def build_meeting_footer(language_code: Optional[str]) -> str:
    """
    Kalimat standar: arahkan user untuk menghubungi tim sales / kantor,
    disesuaikan per bahasa (11 bahasa utama).

    Task 18 (2026-05-13): primary path reads from i18n loader; legacy if/elif
    chain below kept as DEPRECATED fallback (removed in Task 19).
    """
    lc = (language_code or "").strip().lower()[:2]
    try:
        from modules.i18n import t as _t
        return _t("meeting.footer", lc)
    except Exception:
        return (
            "If you would like to schedule a meeting with our team, please contact our sales "
            "team at +62 21–769 8277 or email info@integrity-asia.com."
        )
    # Task 19 (2026-05-13): legacy if/elif chain dead code — superseded by i18n loader above
    lang = (language_code or "").lower()

    if lang.startswith("id"):
        return (
            "Untuk menjadwalkan pertemuan dengan tim kami, Anda dapat langsung "
            "menghubungi tim Sales di +62 21–769 8277 atau email info@integrity-asia.com. "
            "Sampaikan layanan yang ingin didiskusikan serta waktu yang Anda inginkan, dan "
            "tim kami akan menghubungi Anda kembali untuk mengonfirmasi jadwal."
        )
    if lang.startswith("ms"):
        return (
            "Untuk mengatur pertemuan dengan pasukan kami, anda boleh menghubungi pasukan "
            "jualan di +60 3–7931 1323 atau e-mel info@integrity-malaysia.com. "
            "Sila maklumkan jenis perkhidmatan dan masa yang anda inginkan supaya kami "
            "boleh mengesahkan jadual dengan anda."
        )
    if lang.startswith("fr"):
        return (
            "Pour organiser une réunion avec notre équipe, vous pouvez nous contacter "
            "directement par e-mail à info@integrity-asia.com ou par téléphone au "
            "+62 21–769 8277. Indiquez vos disponibilités et vos besoins afin que notre "
            "équipe commerciale puisse vous proposer et confirmer un créneau adapté."
        )
    if lang.startswith("de"):
        return (
            "Um einen Termin mit unserem Team zu vereinbaren, können Sie uns direkt "
            "unter info@integrity-asia.com oder telefonisch unter +62 21–769 8277 "
            "kontaktieren. Teilen Sie uns bitte Ihre Verfügbarkeit und Ihr Anliegen mit, "
            "damit unser Vertriebsteam einen passenden Termin bestätigen kann."
        )
    if lang.startswith("it"):
        return (
            "Per fissare un incontro con il nostro team, può contattarci direttamente "
            "all’indirizzo e-mail info@integrity-asia.com o al numero +62 21–769 8277. "
            "Indichi le sue disponibilità e i servizi di cui desidera parlare, così il "
            "nostro team commerciale potrà proporre e confermare uno slot adatto."
        )
    if lang.startswith("rm"):
        return (
            "Per fixar in inscunter cun nossa squadra, pudais Vus scriver a "
            "info@integrity-asia.com u telefonar al +62 21–769 8277. Inditgai Vossas "
            "disponibilitads e ils servetschs che Vus vulais discutir, uschia che nossa "
            "squadra da vendita po confermar in termin adattà."
        )
    if lang.startswith("ru"):
        return (
            "Чтобы согласовать встречу с нашей командой, вы можете связаться с нами по "
            "электронной почте info@integrity-asia.com или по телефону +62 21–769 8277. "
            "Пожалуйста, укажите удобные для вас даты и время, а также интересующие "
            "услуги, и наша команда продаж предложит и подтвердит подходящий слот."
        )
    if lang.startswith("th"):
        return (
            "หากคุณต้องการนัดประชุมกับทีมของเรา คุณสามารถติดต่อทีมขายได้โดยตรงที่ "
            "info@integrity-asia.com หรือโทร +62 21–769 8277 กรุณาแจ้งช่วงเวลาที่สะดวก "
            "และบริการที่ต้องการพูดคุย เพื่อให้ทีมของเราสามารถเสนอและยืนยันเวลา "
            "นัดหมายที่เหมาะสมให้คุณได้."
        )
    if lang.startswith("es"):
        return (
            "Si desea concertar una reunión con nuestro equipo, puede ponerse en contacto "
            "directamente con nosotros en info@integrity-asia.com o llamar al +62 21–769 8277. "
            "Indíquenos sus horarios disponibles y los servicios que desea tratar para que "
            "nuestro equipo comercial pueda proponer y confirmar una franja adecuada."
        )
    if lang.startswith("pt"):
        return (
            "Para marcar uma reunião com a nossa equipa, pode contactar-nos diretamente "
            "através do e-mail info@integrity-asia.com ou pelo telefone +62 21–769 8277. "
            "Indique a sua disponibilidade e os serviços que pretende discutir para que a "
            "nossa equipa comercial possa propor e confirmar um horário adequado."
        )

    # Default EN
    return (
        "If you would like to schedule a meeting with our team, please contact our sales "
        "team at +62 21–769 8277 or email info@integrity-asia.com. Share your availability "
        "and the services you wish to discuss, and we will propose and confirm a suitable slot."
    )


def build_other_slot_label(language_code: Optional[str]) -> str:
    """
    Localized label for the OTHER_PICKED_SLOT choice in the meeting picker.
    Prefix-match on language_code; English default for unknown codes.

    Task 18 (2026-05-13): primary path reads from i18n loader; legacy below
    is DEPRECATED fallback (removed in Task 19).
    """
    lc = (language_code or "").strip().lower()[:2]
    try:
        from modules.i18n import t as _t
        return _t("meeting.other_slot_label", lc)
    except Exception:
        return "Other Slot Recommendations"
    # Task 19 (2026-05-13): legacy if/elif chain dead code — superseded by i18n loader above
    lang = (language_code or "").lower()

    if lang.startswith("id"): return "Rekomendasi Slot Lainnya"
    if lang.startswith("ms"): return "Cadangan Slot Lain"
    if lang.startswith("fr"): return "Autres créneaux proposés"
    if lang.startswith("de"): return "Weitere Terminvorschläge"
    if lang.startswith("it"): return "Altri orari proposti"
    if lang.startswith("rm"): return "Auters propostas d'uras"
    if lang.startswith("ru"): return "Другие варианты времени"
    if lang.startswith("th"): return "ตัวเลือกเวลาอื่น"
    if lang.startswith("es"): return "Otras franjas horarias"
    if lang.startswith("pt"): return "Outros horários sugeridos"
    return "Other Slot Recommendations"  # en default


def build_meeting_picker_preamble(
    language_code: Optional[str],
    *,
    service_label: Optional[str],
    nickname: Optional[str],
) -> str:
    """
    2-sentence picker preamble in the target language. Sentence 1 is a warm,
    personalized invitation that mentions the service (if provided) and the
    nickname (if provided). Sentence 2 asks the user to pick a slot from the UI.

    Placeholders drop out cleanly when absent (no stray punctuation).
    Prefix-match on language_code; English default for unknown codes.
    """
    lang = (language_code or "").lower()
    nick = (nickname or "").strip() or None
    svc = (service_label or "").strip() or None

    if lang.startswith("id"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" mengenai bagaimana layanan {svc} dapat mendukung kebutuhan bisnis Anda"
            if svc else ""
        )
        return (
            f"Saya dengan senang hati akan berdiskusi lebih lanjut{svc_phrase}{nick_phrase}. "
            f"Silakan pilih waktu pertemuan yang paling sesuai dari pilihan di bawah ini."
        )

    if lang.startswith("ms"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" tentang bagaimana khidmat {svc} kami dapat menyokong keperluan perniagaan anda"
            if svc else ""
        )
        return (
            f"Saya berbesar hati untuk berbincang{svc_phrase}{nick_phrase}. "
            f"Sila pilih masa pertemuan yang sesuai daripada pilihan di bawah."
        )

    if lang.startswith("fr"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" de la manière dont nos services {svc} peuvent répondre à vos besoins"
            if svc else ""
        )
        return (
            f"Je serais ravi(e) de discuter{svc_phrase}{nick_phrase}. "
            f"Veuillez sélectionner le créneau qui vous convient parmi les options ci-dessous."
        )

    if lang.startswith("de"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f", wie unsere {svc}-Leistungen Ihre geschäftlichen Anforderungen unterstützen können"
            if svc else ""
        )
        return (
            f"Ich würde gerne besprechen{svc_phrase}{nick_phrase}. "
            f"Bitte wählen Sie einen passenden Termin aus den unten angezeigten Optionen."
        )

    if lang.startswith("it"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" come i nostri servizi {svc} possono supportare le sue esigenze aziendali"
            if svc else ""
        )
        return (
            f"Sarei lieto/a di discutere{svc_phrase}{nick_phrase}. "
            f"La invito a selezionare l'orario di incontro preferito tra le opzioni qui sotto."
        )

    if lang.startswith("rm"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" co noss servetschs {svc} pon sustegnair Vossas basegns d'affars"
            if svc else ""
        )
        return (
            f"Jau discutess gugent{svc_phrase}{nick_phrase}. "
            f"Per plaschair tschernì in termin adattà tranter las opziuns qua sut."
        )

    if lang.startswith("ru"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f", как наши услуги {svc} могут поддержать ваши бизнес-задачи"
            if svc else ""
        )
        return (
            f"Буду рад(а) обсудить{svc_phrase}{nick_phrase}. "
            f"Пожалуйста, выберите удобное время встречи из предложенных ниже вариантов."
        )

    if lang.startswith("th"):
        nick_phrase = f" คุณ{nick}" if nick else ""
        svc_phrase = (
            f"เกี่ยวกับบริการ {svc} ที่จะช่วยสนับสนุนธุรกิจของคุณ"
            if svc else ""
        )
        return (
            f"ยินดีที่จะได้พูดคุย{svc_phrase}{nick_phrase} "
            f"กรุณาเลือกเวลานัดหมายที่เหมาะสมจากตัวเลือกด้านล่าง"
        )

    if lang.startswith("es"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" cómo nuestros servicios {svc} pueden apoyar las necesidades de su empresa"
            if svc else ""
        )
        return (
            f"Me encantaría hablar sobre{svc_phrase}{nick_phrase}. "
            f"Por favor, seleccione el horario que prefiera entre las opciones disponibles a continuación."
        )

    if lang.startswith("pt"):
        nick_phrase = f", {nick}" if nick else ""
        svc_phrase = (
            f" como os nossos serviços {svc} podem apoiar as necessidades do seu negócio"
            if svc else ""
        )
        return (
            f"Teria todo o gosto em conversar sobre{svc_phrase}{nick_phrase}. "
            f"Por favor, selecione o horário de reunião preferido entre as opções abaixo."
        )

    # en default
    nick_phrase = f", {nick}" if nick else ""
    svc_phrase = (
        f" how our {svc} services can support your business needs"
        if svc else ""
    )
    return (
        f"I'd love to discuss{svc_phrase}{nick_phrase}. "
        f"Please select your preferred meeting time from the available options below."
    )