from __future__ import annotations
from typing import Optional
import re

def is_quotation_request(text: str, language_code: Optional[str]) -> bool:
    """
    Heuristik ringan untuk mendeteksi permintaan quotation/quote/pricelist
    di berbagai bahasa tanpa LLM.
    """
    if not text:
        return False

    t = text.lower()
    lang = (language_code or "").lower()

    # Kata kunci generik lintas bahasa
    generic_kw = [
        "quotation", "quote", "quotes",
        "price list", "pricelist", "price-list",
        "pricing", "price", "cost estimate", "cost estimation",
    ]
    if any(k in t for k in generic_kw):
        return True

    # Tambahan kata kunci spesifik per bahasa
    lang_kw: list[str] = []

    if lang.startswith("id"):
        lang_kw = [
            "penawaran harga", "kirim penawaran", "kirim quotation",
            "daftar harga", "harga jasa", "minta harga", "tolong kirim quotation",
        ]
    elif lang.startswith("ms"):
        lang_kw = [
            "sebut harga", "senarai harga", "quotation harga",
            "minta harga", "kirimkan sebut harga",
        ]
    elif lang.startswith("fr"):
        lang_kw = [
            "devis", "tarif", "proposition commerciale",
            "demande de prix",
        ]
    elif lang.startswith("de"):
        lang_kw = [
            "angebot", "preisangebot", "kostenangebot",
            "preisübersicht", "preis anfrage",
        ]
    elif lang.startswith("it"):
        lang_kw = [
            "preventivo", "offerta economica", "richiesta di prezzo",
        ]
    elif lang.startswith("rm"):
        # Romansh – jaga simple, pakai istilah umum
        lang_kw = [
            "preventiv", "offerta", "offerta da prets",
        ]
    elif lang.startswith("ru"):
        lang_kw = [
            "коммерческое предложение", "расчет стоимости",
            "стоимость услуг", "запрос цены", "запрос коммерческого предложения",
        ]
    elif lang.startswith("th"):
        lang_kw = [
            "ใบเสนอราคา", "ขอใบเสนอราคา", "ราคาบริการ",
        ]
    elif lang.startswith("es"):
        lang_kw = [
            "cotización", "presupuesto", "lista de precios",
            "solicitar precios",
        ]
    elif lang.startswith("pt"):
        lang_kw = [
            "orçamento", "cotação", "lista de preços",
            "solicitar preços",
        ]
    elif lang.startswith("en"):
        # sudah cukup tertangkap generic_kw, tapi bisa tambah:
        lang_kw = [
            "send quotation", "send me a quote", "request a quote",
            "cost proposal", "pricing proposal",
        ]

    if any(k in t for k in lang_kw):
        return True

    # fallback: kalau ada kata "quote/quotation" + "email/send"
    if re.search(r"\b(quote|quotation|devis|angebot|preventivo|cotiza|orçamento)\b", t) and \
       re.search(r"\b(email|mail|send|kirim|envoyer|enviar)\b", t):
        return True

    return False


def build_quotation_footer(language_code: Optional[str]) -> str:
    """
    Kalimat standar: "kami akan siapkan quotation terperinci dan kirim segera".
    Disesuaikan per bahasa. Tambahkan juga arahkan ke tim sales.
    """
    lang = (language_code or "").lower()

    if lang.startswith("id"):
        return (
            "Setelah kami menerima detail kebutuhan Anda, kami akan menyiapkan "
            "quotation terperinci dan mengirimkannya kepada Anda dalam waktu dekat. "
            "Untuk mempercepat proses, Anda juga dapat menghubungi tim sales kami "
            "di +1 (555) 010-0100 atau email info@acmeservices.example.com."
        )
    if lang.startswith("ms"):
        return (
            "Sebaik sahaja kami menerima butiran keperluan anda, kami akan menyediakan "
            "sebut harga terperinci dan mengirimkannya kepada anda dalam masa terdekat. "
            "Untuk mempercepat proses, anda juga boleh menghubungi pasukan jualan kami "
            "di +1 (555) 010-0101 atau info@acmeservices.example.com."
        )
    if lang.startswith("fr"):
        return (
            "Dès que nous aurons reçu le détail de vos besoins, nous préparerons "
            "un devis détaillé et vous l’enverrons dans les plus brefs délais. "
            "Pour toute demande urgente, vous pouvez également contacter notre équipe commerciale "
            "par e-mail à info@acmeservices.example.com."
        )
    if lang.startswith("de"):
        return (
            "Sobald wir Ihre Anforderungen im Detail erhalten haben, erstellen wir "
            "ein detailliertes Angebot und senden es Ihnen in Kürze zu. "
            "Bei dringenden Anfragen können Sie sich auch direkt an unser Vertriebsteam "
            "unter info@acmeservices.example.com wenden."
        )
    if lang.startswith("it"):
        return (
            "Non appena riceveremo i dettagli delle vostre esigenze, prepareremo "
            "un preventivo dettagliato e ve lo invieremo a breve. "
            "Per richieste urgenti potete anche contattare il nostro team commerciale "
            "all’indirizzo info@acmeservices.example.com."
        )
    if lang.startswith("rm"):
        return (
            "Appena che nus vegnin a retschaiver ils detagls da Vossas "
            "pretensiuns, vegnain nus a preparar in preventiv detaglià "
            "e trametter quel a Vus en curt temp. Per dumondas urgentas "
            "pudais Vus era contactar nossa squadra da vendita via "
            "info@acmeservices.example.com."
        )
    if lang.startswith("ru"):
        return (
            "Как только мы получим подробное описание ваших потребностей, "
            "мы подготовим детальное коммерческое предложение и направим его вам "
            "в ближайшее время. По срочным вопросам вы также можете связаться с нашей "
            "командой продаж по адресу info@acmeservices.example.com."
        )
    if lang.startswith("th"):
        return (
            "เมื่อเราได้รับรายละเอียดความต้องการของคุณแล้ว เราจะจัดทำใบเสนอราคาอย่างละเอียด "
            "และส่งให้คุณในเร็ว ๆ นี้ เพื่อความรวดเร็ว คุณสามารถติดต่อทีมขายของเราได้ที่ "
            "info@acmeservices.example.com."
        )
    if lang.startswith("es"):
        return (
            "En cuanto recibamos el detalle de sus necesidades, prepararemos "
            "una cotización detallada y se la enviaremos en breve. "
            "Para solicitudes urgentes también puede contactar a nuestro equipo comercial "
            "en info@acmeservices.example.com."
        )
    if lang.startswith("pt"):
        return (
            "Assim que recebermos os detalhes das suas necessidades, prepararemos "
            "um orçamento detalhado e o enviaremos em breve. "
            "Para pedidos urgentes, também pode contactar a nossa equipa comercial em "
            "info@acmeservices.example.com."
        )

    # default (EN)
    return (
        "Once we receive your detailed requirements, we will prepare a detailed "
        "quotation and send it to you shortly. For urgent requests, you can also "
        "contact our sales team at info@acmeservices.example.com."
    )