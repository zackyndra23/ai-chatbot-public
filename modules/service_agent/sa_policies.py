SERVICE_AGENT_PREFIX = "SA_SELECT_"

VALUE_TO_FLOW_CODE = {
    "General": "GRL",
    "EBS": "EBS",
    "WBS": "WBS",
    "DD": "DDC",
    "Mystery Shopping": "MSG",
    "Asset Verification": "AST",
    "Contact Verification": "SKT",
    "Fraud Investigation": "FRI",
    # 2026-05-18: "Insurance Investigation" kept for back-compat; the real
    # SERVICE_VALUE_CODE_MAP key is "Claim Investigation" — alias both so the
    # SERVICE_CODE_TO_FLOW_CODE derivation resolves
    # `claim_investigation → CLI` once the flow exists.
    "Insurance Investigation": "CLI",
    "Claim Investigation": "CLI",
    "Market Research": "MSY",
    "Non-Use Investigation": "NUI",
    # 2026-05-18: "Anti-Counterfeiting" kept for back-compat; the real
    # SERVICE_VALUE_CODE_MAP key is "Counterfeit Investigation" — alias both
    # so the SERVICE_CODE_TO_FLOW_CODE derivation resolves
    # `anti-counterfeiting_investigation → ACI`.
    "Anti-Counterfeiting": "ACI",
    "Counterfeit Investigation": "ACI",
    "Parallel Trading": "PTI",
    "ABMS E-Learning": "ABMS",
    # 2026-05-18: Trademark Investigation flow is built as `CMI` in
    # `sa_flows.build_cmi_flow` (`service_label="Trademark Investigation"`).
    # Earlier value "TDI" pointed to a flow that was never built → KeyError on
    # SA_SELECT_trademark_investigation. Map directly to CMI.
    "Trademark Investigation": "CMI",
    "Know Your Customer": "KYC",
}

SERVICE_VALUE_CODE_MAP = {
    "General": "general_service",
    "EBS": "background_check",
    "WBS": "whistleblowing_hotline",
    "DD": "due_diligence",
    "Mystery Shopping": "mystery_shopping",
    "Asset Verification": "asset_verification",
    "Contact Verification": "contact_verification",
    "Fraud Investigation": "fraud_investigation",
    "Claim Investigation": "claim_investigation",
    "Market Research": "market_research",
    "Non-Use Investigation": "non-use_investigation",
    "Counterfeit Investigation": "anti-counterfeiting_investigation",
    "Parallel Trading": "parallel_trading_investigation",
    "ABMS E-Learning": "abms_eLearning",
    "Trademark Investigation": "trademark_investigation",
    "Know Your Customer": "know_your_customer",
}

SERVICE_LABEL_CODE_MAP = {
    "general_service": "General Service",
    "background_check": "Background Check",
    "whistleblowing_hotline": "Whistleblowing Hotline",
    "due_diligence": "Due Diligence",
    "mystery_shopping": "Mystery Shopping",
    "asset_verification": "Asset Verification",
    "contact_verification": "Contact Verification",
    "fraud_investigation": "Fraud Investigation",
    "claim_investigation": "Claim Investigation",
    "market_research": "Market Research",
    "non-use_investigation": "Non-Use Investigation",
    "anti-counterfeiting_investigation": "Anti-Counterfeiting Investigation",
    "parallel_trading_investigation": "Parallel Trading Investigation",
    "abms_eLearning": "ABMS E-Learning",
    "trademark_investigation": "Trademark Investigation",
    "know_your_customer": "Know Your Customer",
}

MAX_AMBIGUOUS_RETRY = 2

# sa_policies.py

SERVICE_CODE_TO_FLOW_CODE = {
    # derive dari SERVICE_VALUE_CODE_MAP + VALUE_TO_FLOW_CODE
    SERVICE_VALUE_CODE_MAP[k]: VALUE_TO_FLOW_CODE[k]
    for k in SERVICE_VALUE_CODE_MAP.keys()
    if k in VALUE_TO_FLOW_CODE
}

# kalau sd_system detect `route=incontext` & related_services > 0
# dan belum ada AgentSessionState aktif -> boleh trigger ServiceAgent.