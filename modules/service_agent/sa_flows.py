from .sa_types import QuestionStep, Choice

def build_ebs_flow() -> dict[str, QuestionStep]:
    return {
        "ebs.candidate_countries_1": QuestionStep(
            id="ebs.candidate_countries_1",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Scope Specification",
            order=1,
            field_name="ebs_candidate_countries",
            text="In which country or countries are your candidates currently based, or have they studied or worked?",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={
            # #     "yes_ebs": "ebs.context_2",
            # #     "no_other": "route_other_service",
            # # },
            default_next="ebs.checks_needed_3",
        ),
        
        # "ebs.context_purpose_2": QuestionStep(
        #     id="ebs.context_purpose_2",
        #     service_code="EBS",
        #     service_label="Employment Background Screening",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="ebs_context_purpose",
        #     text="Are you looking for employment background screening for your candidates or existing employees?",
        #     type="string",
        #     # choices=[
        #     #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
        #     # ],
        #     # # next_if={},
        #     default_next="ebs.checks_needed_3",
        # ),

        "ebs.checks_needed_3": QuestionStep(
            id="ebs.checks_needed_3",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Investigation Parameter",
            order=3,
            field_name="ebs_checks_needed",
            text="Do you already know which checks you need (employment, education, criminal, reference, ID, etc.), or would you like us to recommend suitable packages?",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={
            # #     "one_time": "ebs.org_1",
            # #     "ongoing": "ebs.org_1",
            # #     "unsure": "ebs.org_1",
            # # },
            default_next="ebs.volume_estimate_4",
        ),

        "ebs.volume_estimate_4": QuestionStep(
            id="ebs.volume_estimate_4",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Scope Specification",
            order=4,
            field_name="ebs_volume_estimate",
            text="Roughly how many candidates do you expect to screen per month or per year?",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            # default_next="ebs.contact_details_5",
            default_next="ebs.position_types_7",
            # default_next=None,
        ),

        # "ebs.contact_details_5": QuestionStep(
        #     id="ebs.contact_details_5",
        #     service_code="EBS",
        #     service_label="Employment Background Screening",
        #     section="Next Steps & Contact",
        #     order=5,
        #     field_name="ebs_contact_details",
        #     text="Would you like us to prepare a tailored proposal? If yes, what is the best email address and phone/WhatsApp number to send it to?",
        #     type="string",
        #     # choices=[
        #     #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
        #     # ],
        #     # # next_if={},
        #     default_next="ebs.budget_preference_6",
        # ),

        # "ebs.budget_preference_6": QuestionStep(
        #     id="ebs.budget_preference_6",
        #     service_code="EBS",
        #     service_label="Employment Background Screening",
        #     section="Budget & next steps",
        #     order=6,
        #     field_name="ebs_budget_preference",
        #     text="Do you already have a budget range per candidate, or would you prefer that we propose options based on your volume and checks?",
        #     type="string",
        #     # choices=[
        #     #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
        #     # ],
        #     # # next_if={},
        #     default_next="ebs.position_types_7",
        # ),

        "ebs.position_types_7": QuestionStep(
            id="ebs.position_types_7",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Scope Specification",
            order=7,
            field_name="ebs_position_types",
            text="For which types of positions do you need background checks? (staff, managers, executives, high-risk roles, etc.)",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next="ebs.process_preference_8",
        ),

        "ebs.process_preference_8": QuestionStep(
            id="ebs.process_preference_8",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Investigation Parameter",
            order=8,
            field_name="ebs_process_preference",
            text="How would you like the process to work: 1. Your team inputs candidate data; 2 The candidate fills in a form directly; 3. Or a mix of both?",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next="ebs.project_type_9",
        ),

        "ebs.project_type_9": QuestionStep(
            id="ebs.project_type_9",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Context Confirmation",
            order=9,
            field_name="ebs_project_type",
            text="Is this for a one-time project or for ongoing hiring?",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next="ebs.user_role_10",
        ),

        "ebs.user_role_10": QuestionStep(
            id="ebs.user_role_10",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Organization & role",
            order=10,
            field_name="ebs_user_role",
            text="What is your role in the company? (HR, recruitment, compliance, procurement, etc.)",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next="ebs.company_profile_11",
        ),

        "ebs.company_profile_11": QuestionStep(
            id="ebs.company_profile_11",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Organization & role",
            order=11,
            field_name="ebs_company_profile",
            text="Can you briefly tell me about your company, industry, and where you are headquartered?",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next="ebs.compliance_requirements_12",
        ),

        "ebs.compliance_requirements_12": QuestionStep(
            id="ebs.compliance_requirements_12",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Timeline & Priorities",
            order=12,
            field_name="ebs_compliance_requirements",
            text="Are there any compliance or data protection requirements we should follow? (e.g. PDPL, GDPR, internal group policies)",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next="ebs.tat_expectation_13",
        ),

        "ebs.tat_expectation_13": QuestionStep(
            id="ebs.tat_expectation_13",
            service_code="EBS",
            service_label="Employment Background Screening",
            section="Timeline & Priorities",
            order=13,
            field_name="ebs_tat_expectation",
            text="What is your expected turnaround time for a full report? (for example 3 - 5 or 7 - 10 working days)",
            type="string",
            # choices=[
            #     Choice(value="ebs_sa_switch", label="More Services", selected=False),
            # ],
            # # next_if={},
            default_next=None,
        ),
    }

def build_ddc_flow() -> dict[str, QuestionStep]:
    return {
        "ddc.target_operating_countries_1": QuestionStep(
            id="ddc.target_operating_countries_1",
            service_code="DDC",
            service_label="Due Diligence",
            section="Scope Specification",
            order=1,
            field_name="ddc_target_operating_countries",
            text="In which country or countries does the target mainly operate?",
            type="string",
            default_next="ddc.main_objective_3",
        ),

        # "ddc.context_confirmation_2": QuestionStep(
        #     id="ddc.context_confirmation_2",
        #     service_code="DDC",
        #     service_label="Due Diligence",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="ddc_context_confirmation",
        #     text=(
        #         "Are you looking for reputational due diligence on a company or group of companies?"
        #     ),
        #     type="string",
        #     default_next="ddc.main_objective_3",
        # ),

        "ddc.main_objective_3": QuestionStep(
            id="ddc.main_objective_3",
            service_code="DDC",
            service_label="Due Diligence",
            section="Context Confirmation",
            order=3,
            field_name="ddc_main_objective",
            text=(
                "What is the main objective? For example:\n"
                "- New client/vendor/distributor onboarding\n"
                "- Pre-transaction (M&A, JV, investment)\n"
                "- Review of an existing partner\n"
                "- Internal risk assessment / investigation"
            ),
            type="string",
            default_next="ddc.single_or_group_4",
        ),

        "ddc.single_or_group_4": QuestionStep(
            id="ddc.single_or_group_4",
            service_code="DDC",
            service_label="Due Diligence",
            section="Scope Specification",
            order=4,
            field_name="ddc_single_or_group",
            text="Is this for one company only, or for several related companies / subsidiaries?",
            type="string",
            default_next="ddc.target_company_names_5",
        ),

        "ddc.target_company_names_5": QuestionStep(
            id="ddc.target_company_names_5",
            service_code="DDC",
            service_label="Due Diligence",
            section="Scope Specification",
            order=5,
            field_name="ddc_target_company_names",
            text="What is the name of the company (or companies) you would like us to review?",
            type="string",
            default_next="ddc.focus_entities_6",
        ),

        "ddc.focus_entities_6": QuestionStep(
            id="ddc.focus_entities_6",
            service_code="DDC",
            service_label="Due Diligence",
            section="Investigation Parameter",
            order=6,
            field_name="ddc_focus_entities",
            text=(
                "Do you want us to focus on:\n"
                "- The company only,\n"
                "- Company + shareholders, or\n"
                "- Company + shareholders + key executives/directors?"
            ),
            type="string",
            default_next="ddc.depth_level_7",
        ),

        "ddc.depth_level_7": QuestionStep(
            id="ddc.depth_level_7",
            service_code="DDC",
            service_label="Due Diligence",
            section="Investigation Parameter",
            order=7,
            field_name="ddc_depth_level",
            text=(
                "What level of depth are you looking for:\n"
                "- Basic screening (sanctions, PEP, adverse media)\n"
                "- Standard reputational due diligence\n"
                "- Enhanced due diligence (including discreet human source enquiries)?"
            ),
            type="string",
            default_next="ddc_client_company_profile_8",
        ),

        "ddc_client_company_profile_8": QuestionStep(
            id="ddc_client_company_profile_8",
            service_code="DDC",
            service_label="Due Diligence",
            section="Organization & role",
            order=8,
            field_name="ddc_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="ddc_user_role_9",
        ),

        "ddc_user_role_9": QuestionStep(
            id="ddc_user_role_9",
            service_code="DDC",
            service_label="Due Diligence",
            section="Organization & role",
            order=9,
            field_name="ddc_user_role",
            text="What is your role in the organization? (compliance, legal, risk, procurement, investment, etc.)",
            type="string",
            # default_next="ddc_budget_preference_10",
            default_next="ddc_future_due_diligence_11",
        ),

        # "ddc_budget_preference_10": QuestionStep(
        #     id="ddc_budget_preference_10",
        #     service_code="DDC",
        #     service_label="Due Diligence",
        #     section="Budget & next steps",
        #     order=10,
        #     field_name="ddc_budget_preference",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on scope and depth?",
        #     type="string",
        #     default_next="ddc_future_due_diligence_11",
        # ),

        "ddc_future_due_diligence_11": QuestionStep(
            id="ddc_future_due_diligence_11",
            service_code="DDC",
            service_label="Due Diligence",
            section="Next Steps & Contact",
            order=11,
            field_name="ddc_future_due_diligence",
            text="Is this likely to be a one-off assignment, or do you foresee similar due diligences in the future?",
            type="string",
            # default_next="ddc_contact_details_12",
            default_next="ddc_specific_risks_13",
        ),

        # "ddc_contact_details_12": QuestionStep(
        #     id="ddc_contact_details_12",
        #     service_code="DDC",
        #     service_label="Due Diligence",
        #     section="Next Steps & Contact",
        #     order=12,
        #     field_name="ddc_contact_details",
        #     text="Would you like us to prepare a tailored proposal? If yes, what is the best email address and phone/WhatsApp number to send it to?",
        #     type="string",
        #     default_next="ddc_specific_risks_13",
        # ),

        "ddc_specific_risks_13": QuestionStep(
            id="ddc_specific_risks_13",
            service_code="DDC",
            service_label="Due Diligence",
            section="Investigation Parameter",
            order=13,
            field_name="ddc_specific_risks",
            text="Are there any specific risks you want us to focus on (e.g. corruption/bribery, fraud, litigation/regulatory, political exposure, labor issues, reputation with clients/suppliers)?",
            type="string",
            default_next="ddc_deliverable_preference_14",
        ),

        "ddc_deliverable_preference_14": QuestionStep(
            id="ddc_deliverable_preference_14",
            service_code="DDC",
            service_label="Due Diligence",
            section="Budget & next steps",
            order=14,
            field_name="ddc_deliverable_preference",
            text="What type of deliverable do you prefer: a short red-flag summary, a full narrative report, or both?",
            type="string",
            default_next="ddc_deadline_15",
        ),

        "ddc_deadline_15": QuestionStep(
            id="ddc_deadline_15",
            service_code="DDC",
            service_label="Due Diligence",
            section="Timeline & Priorities",
            order=15,
            field_name="ddc_deadline",
            text="What is your ideal deadline for receiving the report, and is it linked to any fixed date (committee, signing, closing)?",
            type="string",
            default_next=None,  # selesai → completed
        ),
    }

def build_msg_flow() -> dict[str, QuestionStep]:
    return {
        "msg.location_scope_1": QuestionStep(
            id="msg.location_scope_1",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Scope Specification",
            order=1,
            field_name="msg_location_scope",
            text="In which country, cities, or regions would you like to conduct the mystery shopping?",
            type="string",
            default_next="msg.main_objective_2",
        ),

        "msg.main_objective_2": QuestionStep(
            id="msg.main_objective_2",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Context Confirmation",
            order=2,
            field_name="msg_main_objective",
            text="What is the main objective of mystery shopping? (e.g. service quality, SOP/brand compliance, promotion checks, integrity/compliance, other)",
            type="string",
            default_next="msg.top3_metrics_3",
            # default_next=None,
        ),

        "msg.top3_metrics_3": QuestionStep(
            id="msg.top3_metrics_3",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Investigation Parameter",
            order=3,
            field_name="msg_top3_metrics",
            text="What are the top 3 things you want to measure? (e.g. friendliness, waiting time, product knowledge, SOP compliance, complaint handling)",
            type="string",
            default_next="msg.simulated_situations_4",
        ),

        "msg.simulated_situations_4": QuestionStep(
            id="msg.simulated_situations_4",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Investigation Parameter",
            order=4,
            field_name="msg_simulated_situations",
            text="What kind of customer situations do you want to simulate? (new customer, complaint, product enquiry, promotion enquiry, etc.)",
            type="string",
            default_next="msg.volume_per_wave_5",
        ),

        "msg.volume_per_wave_5": QuestionStep(
            id="msg.volume_per_wave_5",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Timeline & Priorities",
            order=5,
            field_name="msg_volume_per_wave",
            text="Roughly how many visits or contacts do you expect per month or per wave?",
            type="string",
            default_next="msg.num_outlets_6",
        ),

        "msg.num_outlets_6": QuestionStep(
            id="msg.num_outlets_6",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Scope Specification",
            order=6,
            field_name="msg_num_outlets",
            text="Approximately how many outlets or customer touchpoints would you like to include?",
            type="string",
            default_next="msg.first_wave_start_7",
        ),

        "msg.first_wave_start_7": QuestionStep(
            id="msg.first_wave_start_7",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Timeline & Priorities",
            order=7,
            field_name="msg_first_wave_start",
            text="When would you like the first wave of mystery shopping to start?",
            type="string",
            # default_next="msg.budget_8",
            default_next="msg.context_confirmation_9",
        ),

        # "msg.budget_8": QuestionStep(
        #     id="msg.budget_8",
        #     service_code="MSG",
        #     service_label="Mystery Shopping",
        #     section="Budget & next steps",
        #     order=8,
        #     field_name="msg_budget",
        #     text="Do you have a budget range in mind, or would you like us to propose a couple of options based on volume and frequency?",
        #     type="string",
        #     default_next="msg.context_confirmation_9",
        # ),

        "msg.context_confirmation_9": QuestionStep(
            id="msg.context_confirmation_9",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Context Confirmation",
            order=9,
            field_name="msg_context_confirmation",
            text="To make sure I guide you properly: are you interested in mystery shopping / mystery audits for your outlets or services?",
            type="string",
            default_next="msg.program_type_10",
        ),

        "msg.program_type_10": QuestionStep(
            id="msg.program_type_10",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Timeline & Priorities",
            order=10,
            field_name="msg_program_type",
            text="Is this a one-time project, a pilot, or an ongoing program (monthly/quarterly)?",
            type="string",
            default_next="msg.channels_11",
        ),

        "msg.channels_11": QuestionStep(
            id="msg.channels_11",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Scope Specification",
            order=11,
            field_name="msg_channels",
            text="Which channels do you want to assess? (branches/stores, call center, WhatsApp/chat, website, mobile app)",
            type="string",
            default_next="msg.company_profile_12",
        ),

        "msg.company_profile_12": QuestionStep(
            id="msg.company_profile_12",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Organization & role",
            order=12,
            field_name="msg_company_profile",
            text="Can you tell me briefly about your company and industry?",
            type="string",
            default_next="msg.user_role_13",
        ),

        "msg.user_role_13": QuestionStep(
            id="msg.user_role_13",
            service_code="MSG",
            service_label="Mystery Shopping",
            section="Organization & role",
            order=13,
            field_name="msg_user_role",
            text="What is your role in the company? (operations, quality, marketing, compliance, audit, etc.)",
            type="string",
            # default_next="msg.contact_details_14",
            default_next=None,  # selesai → completed
        ),

        # "msg.contact_details_14": QuestionStep(
        #     id="msg.contact_details_14",
        #     service_code="MSG",
        #     service_label="Mystery Shopping",
        #     section="Next Steps & Contact",
        #     order=14,
        #     field_name="msg_contact_details",
        #     text="What is the best email address and phone/WhatsApp number so we can send you a tailored proposal?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_ast_flow() -> dict[str, QuestionStep]:
    return {
        "ast.target_asset_countries_1": QuestionStep(
            id="ast.target_asset_countries_1",
            service_code="AST",
            service_label="Asset Tracing",
            section="Investigation Parameter",
            order=1,
            field_name="ast_target_asset_countries",
            text="In which country or countries do you believe the target may have assets or business interests?",
            type="string",
            default_next="ast.main_objective_3",
        ),

        # "ast.context_confirmation_2": QuestionStep(
        #     id="ast.context_confirmation_2",
        #     service_code="AST",
        #     service_label="Asset Tracing",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="ast_context_confirmation",
        #     text=(
        #         "Are you looking for asset tracing / asset investigations to identify assets belonging to an individual or a company?"
        #     ),
        #     type="string",
        #     default_next="ast.main_objective_3",
        # ),

        "ast.main_objective_3": QuestionStep(
            id="ast.main_objective_3",
            service_code="AST",
            service_label="Asset Tracing",
            section="Context Confirmation",
            order=3,
            field_name="ast_main_objective",
            text=(
                "What is the main objective of asset tracing? For example:\n"
                "- Debt recovery or unpaid invoices\n"
                "- Enforcement of a court judgment or arbitration award\n"
                "- Pre-litigation assessment (to see if its worth suing)\n"
                "- Internal investigation or fraud case\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="ast.asset_types_of_interest_4",
        ),

        "ast.asset_types_of_interest_4": QuestionStep(
            id="ast.asset_types_of_interest_4",
            service_code="AST",
            service_label="Asset Tracing",
            section="Investigation Parameter",
            order=4,
            field_name="ast_asset_types_of_interest",
            text=(
                "Are there any particular types of assets you are interested in? For example:\n"
                "- Real estate / properties\n"
                "- Shareholdings in companies\n"
                "- Business interests / partnerships\n"
                "- Vehicles, vessels, high-value movables\n"
                "- Intellectual property or brands"
            ),
            type="string",
            default_next="ast.target_identity_and_relationship_5",
        ),

        "ast.target_identity_and_relationship_5": QuestionStep(
            id="ast.target_identity_and_relationship_5",
            service_code="AST",
            service_label="Asset Tracing",
            section="Scope Specification",
            order=5,
            field_name="ast_target_identity_and_relationship",
            text="What is the name of the person/company, and what is your relationship with them (debtor, former partner, vendor, client, etc.)",
            type="string",
            default_next="ast.legal_stage_6",
        ),

        "ast.legal_stage_6": QuestionStep(
            id="ast.legal_stage_6",
            service_code="AST",
            service_label="Asset Tracing",
            section="Investigation Parameter",
            order=6,
            field_name="ast_legal_stage",
            text="Have you already started legal action or obtained a judgment / arbitration award, or are you still at the pre-litigation stage?",
            type="string",
            default_next="ast.depth_level_7",
        ),

        "ast.depth_level_7": QuestionStep(
            id="ast.depth_level_7",
            service_code="AST",
            service_label="Asset Tracing",
            section="Timeline & Priorities",
            order=7,
            field_name="ast_depth_level",
            text=(
                "What level of depth are you looking for:\n"
                "- A basic desktop mapping of known assets and interests, or\n"
                "- A more in-depth investigation with discreet enquiries and field work?"
            ),
            type="string",
            default_next="ast.deliverable_preference_8",
        ),

        "ast.deliverable_preference_8": QuestionStep(
            id="ast.deliverable_preference_8",
            service_code="AST",
            service_label="Asset Tracing",
            section="Budget & next steps",
            order=8,
            field_name="ast_deliverable_preference",
            text=(
                "What kind of deliverable do you prefer:\n"
                "- A concise asset map / summary, or\n"
                "- A detailed report with sources and recommendations for enforcement, or\n"
                "- Both?"
            ),
            type="string",
            default_next="ast.future_cases_9",
        ),

        "ast.future_cases_9": QuestionStep(
            id="ast.future_cases_9",
            service_code="AST",
            service_label="Asset Tracing",
            section="Next Steps & Contact",
            order=9,
            field_name="ast_future_cases",
            text="Is this a one-off case, or do you expect similar asset tracing matters in the future?",
            type="string",
            # default_next="ast.budget_range_10",
            default_next="st.client_company_profile_11",
        ),

        # "ast.budget_range_10": QuestionStep(
        #     id="ast.budget_range_10",
        #     service_code="AST",
        #     service_label="Asset Tracing",
        #     section="Budget & next steps",
        #     order=10,
        #     field_name="ast_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on countries, depth and timelines?",
        #     type="string",
        #     default_next="ast.client_company_profile_11",
        # ),

        "ast.client_company_profile_11": QuestionStep(
            id="ast.client_company_profile_11",
            service_code="AST",
            service_label="Asset Tracing",
            section="Organization & role",
            order=11,
            field_name="ast_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="ast.user_role_12",
        ),

        "ast.user_role_12": QuestionStep(
            id="ast.user_role_12",
            service_code="AST",
            service_label="Asset Tracing",
            section="Organization & role",
            order=12,
            field_name="ast_user_role",
            text="What is your role in this matter? (legal, finance, risk, owner/shareholder, external lawyer, etc.)",
            type="string",
            # default_next="ast.contact_details_13",
            default_next="ast.amount_at_stake_14",
        ),

        # "ast.contact_details_13": QuestionStep(
        #     id="ast.contact_details_13",
        #     service_code="AST",
        #     service_label="Asset Tracing",
        #     section="Next Steps & Contact",
        #     order=13,
        #     field_name="ast_contact_details",
        #     text="Would you like us to prepare a tailored proposal? If yes, what is the best email address and phone/WhatsApp number to send it to?",
        #     type="string",
        #     default_next="ast.amount_at_stake_14",
        # ),

        "ast.amount_at_stake_14": QuestionStep(
            id="ast.amount_at_stake_14",
            service_code="AST",
            service_label="Asset Tracing",
            section="Scope Specification",
            order=14,
            field_name="ast_amount_at_stake",
            text="What is the approximate amount at stake (claim, exposure or estimated loss)?",
            type="string",
            default_next="ast.method_constraints_15",
        ),

        "ast.method_constraints_15": QuestionStep(
            id="ast.method_constraints_15",
            service_code="AST",
            service_label="Asset Tracing",
            section="Timeline & Priorities",
            order=15,
            field_name="ast_method_constraints",
            text="Do you have any constraints on the methods we use (for example, must be strictly non-contact / open-source only, or are discreet enquiries acceptable)?",
            type="string",
            default_next=None,  # selesai → completed
        ),
    }

def build_wbs_flow() -> dict[str, QuestionStep]:
    return {
        "wbs.availability_countries_1": QuestionStep(
            id="wbs.availability_countries_1",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Scope Specification",
            order=1,
            field_name="wbs_availability_countries",
            text="In which country or countries do you need the system to be available?",
            type="string",
            default_next="wbs.user_eligibility_2",
        ),

        "wbs.user_eligibility_2": QuestionStep(
            id="wbs.user_eligibility_2",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Scope Specification",
            order=2,
            field_name="wbs_user_eligibility",
            text=(
                "Who should be able to use the whistleblowing channel:\n"
                "- Employees only,\n"
                "- Employees + contractors,\n"
                "- Employees + external parties (suppliers, customers, partners)?"
            ),
            type="string",
            default_next="wbs.channels_3",
        ),

        "wbs.channels_3": QuestionStep(
            id="wbs.channels_3",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Investigation Parameter",
            order=3,
            field_name="wbs_channels",
            text=(
                "Which channels are you interested in:\n"
                "- Web reporting form\n"
                "- Email\n"
                "- Telephone hotline\n"
                "- WhatsApp / chat\n"
                "- QR codes / mobile access?"
            ),
            type="string",
            default_next="wbs.languages_4",
            # default_next=None,
        ),

        "wbs.languages_4": QuestionStep(
            id="wbs.languages_4",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Timeline & Priorities",
            order=4,
            field_name="wbs_languages",
            text="In which languages do you need the platform and/or reporting forms to be available?",
            type="string",
            default_next="wbs.launch_timeline_5",
        ),

        "wbs.launch_timeline_5": QuestionStep(
            id="wbs.launch_timeline_5",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Timeline & Priorities",
            order=5,
            field_name="wbs_launch_timeline",
            text="When would you ideally like to launch or upgrade your whistleblowing system? (approximate month or deadline)",
            type="string",
            default_next="wbs.main_objective_6",
        ),

        "wbs.main_objective_6": QuestionStep(
            id="wbs.main_objective_6",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Context Confirmation",
            order=6,
            field_name="wbs_main_objective",
            text=(
                "What is the main objective of the whistleblowing setup? For example:\n"
                "- Compliance with laws/regulations (e.g. anti-corruption, data protection, sector rules)\n"
                "- Group / HQ policy requirement\n"
                "- Strengthen ethics & integrity / speak-up culture\n"
                "- Replace an existing hotline or tool\n"
                "- Respond to a specific incident or risk"
            ),
            type="string",
            default_next="wbs.entities_coverage_7",
        ),

        "wbs.entities_coverage_7": QuestionStep(
            id="wbs.entities_coverage_7",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Scope Specification",
            order=7,
            field_name="wbs_entities_coverage",
            text="Do you need multiple entities / business units covered under one solution, or mainly one legal entity?",
            type="string",
            default_next="wbs.case_handlers_8",
        ),

        "wbs.case_handlers_8": QuestionStep(
            id="wbs.case_handlers_8",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Investigation Parameter",
            order=8,
            field_name="wbs_case_handlers",
            text=(
                "Who should receive and handle the cases on your side:\n"
                "- Compliance / Ethics\n"
                "- HR\n"
                "- Legal / Internal Audit\n"
                "- Local management, HQ, or both?"
            ),
            type="string",
            default_next="wbs.company_profile_9",
        ),

        "wbs.company_profile_9": QuestionStep(
            id="wbs.company_profile_9",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Organization & role",
            order=9,
            field_name="wbs_company_profile",
            text="Can you briefly describe your company and industry, and where your HQ is based?",
            type="string",
            default_next="wbs.employee_and_countries_10",
        ),

        "wbs.employee_and_countries_10": QuestionStep(
            id="wbs.employee_and_countries_10",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Organization & role",
            order=10,
            field_name="wbs_employee_and_countries",
            text="Approximately how many employees do you have, and in how many countries?",
            type="string",
            default_next="wbs.features_needed_11",
        ),

        "wbs.features_needed_11": QuestionStep(
            id="wbs.features_needed_11",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Budget & next steps",
            order=11,
            field_name="wbs_features_needed",
            text=(
                "Besides receiving reports, do you also need:\n"
                "- Case management (tracking, status, actions),\n"
                "- Reporting & statistics for management,\n"
                "- Training/communication support for launch?"
            ),
            type="string",
            default_next="wbs_solution_term_12",
        ),

        "wbs_solution_term_12": QuestionStep(
            id="wbs_solution_term_12",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Budget & next steps",
            order=12,
            field_name="wbs_solution_term",
            text="Do you see this as a long-term solution (multi-year) or a shorter-term implementation?",
            type="string",
            # default_next="wbs_budget_range_13",
            default_next="wbs_existing_provider_14",
        ),

        # "wbs_budget_range_13": QuestionStep(
        #     id="wbs_budget_range_13",
        #     service_code="WBS",
        #     service_label="Whistleblowing System",
        #     section="Budget & next steps",
        #     order=13,
        #     field_name="wbs_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on the number of employees, countries and channels?",
        #     type="string",
        #     default_next="wbs_existing_provider_14",
        # ),

        "wbs_existing_provider_14": QuestionStep(
            id="wbs_existing_provider_14",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Next Steps & Contact",
            order=14,
            field_name="wbs_existing_provider",
            text="Are you replacing an existing provider, or is this your first whistleblowing system?",
            type="string",
            default_next="wbs_anonymity_mode_15",
        ),

        "wbs_anonymity_mode_15": QuestionStep(
            id="wbs_anonymity_mode_15",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Investigation Parameter",
            order=15,
            field_name="wbs_anonymity_mode",
            text="Do you want to allow anonymous reports, or only confidential (identified) reports, or both?",
            type="string",
            default_next="wbs_proposal_summary_request_16",
        ),

        "wbs_proposal_summary_request_16": QuestionStep(
            id="wbs_proposal_summary_request_16",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Next Steps & Contact",
            order=16,
            field_name="wbs_proposal_summary_request",
            text="Would you like us to prepare a tailored proposal summarizing scope (employees, countries, channels, features)?",
            type="string",
            default_next="wbs_regulations_and_policies_17",
        ),

        "wbs_regulations_and_policies_17": QuestionStep(
            id="wbs_regulations_and_policies_17",
            service_code="WBS",
            service_label="Whistleblowing System",
            section="Timeline & Priorities",
            order=17,
            field_name="wbs_regulations_and_policies",
            text="Are there any specific regulations or internal policies we must align with? (e.g. group code of conduct, PDPL/GDPR, sector rules, works council/union expectations)",
            type="string",
            # default_next="wbs_contact_details_18",
            default_next=None,  # selesai → completed
        ),

        # "wbs_contact_details_18": QuestionStep(
        #     id="wbs_contact_details_18",
        #     service_code="WBS",
        #     service_label="Whistleblowing System",
        #     section="Next Steps & Contact",
        #     order=18,
        #     field_name="wbs_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and follow up with you?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_fri_flow() -> dict[str, QuestionStep]:
    return {
        "fri.event_countries_1": QuestionStep(
            id="fri.event_countries_1",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Scope Specification",
            order=1,
            field_name="fri_event_countries",
            text="In which country or countries did the events mainly occur, or where are the key people/companies located?",
            type="string",
            default_next="fri.main_objective_3",
        ),

        # "fri.context_confirmation_2": QuestionStep(
        #     id="fri.context_confirmation_2",
        #     service_code="FRI",
        #     service_label="Fraud Investigation",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="fri_context_confirmation",
        #     text=(
        #         "Are you looking for support with a fraud investigation involving an individual, a group, or a company?"
        #     ),
        #     type="string",
        #     default_next="fri.main_objective_3",
        # ),

        "fri.main_objective_3": QuestionStep(
            id="fri.main_objective_3",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Context Confirmation",
            order=3,
            field_name="fri_main_objective",
            text=(
                "What is the main objective of the investigation? For example:\n"
                "- Confirm whether fraud has occurred\n"
                "- Identify the people involved and their roles\n"
                "- Quantify the loss\n"
                "- Collect evidence for internal disciplinary action\n"
                "- Collect evidence for police / legal action\n"
                "- Support recovery of assets / funds"
            ),
            type="string",
            default_next="fri.main_target_4",
        ),

        "fri.main_target_4": QuestionStep(
            id="fri.main_target_4",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Scope Specification",
            order=4,
            field_name="fri_main_target",
            text=(
                "Who is the main target of the investigation:\n"
                "- An employee,\n"
                "- A group of employees,\n"
                "- A vendor/supplier,\n"
                "- A client,\n"
                "- Another third party?"
            ),
            type="string",
            default_next="fri_case_summary_5",
        ),

        "fri_case_summary_5": QuestionStep(
            id="fri_case_summary_5",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Scope Specification",
            order=5,
            field_name="fri_case_summary",
            text="Can you briefly describe what happened or what you suspect (in a few sentences)?",
            type="string",
            default_next="fri.internal_steps_6",
        ),

        "fri.internal_steps_6": QuestionStep(
            id="fri.internal_steps_6",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Investigation Parameter",
            order=6,
            field_name="fri_internal_steps",
            text=(
                "Have you already taken any internal steps? For example:\n"
                "- Internal review or audit\n"
                "- Interviews\n"
                "- Suspension of staff\n"
                "- Change of system access or controls\n"
                "- None yet"
            ),
            type="string",
            default_next="fri.available_evidence_7",
        ),

        "fri.available_evidence_7": QuestionStep(
            id="fri.available_evidence_7",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Investigation Parameter",
            order=7,
            field_name="fri_available_evidence",
            text="Do you already have any evidence or indications (emails, documents, system logs, screenshots, witness statements, etc.) that we should consider?",
            type="string",
            default_next="fri_primary_focus_8",
        ),

        "fri_primary_focus_8": QuestionStep(
            id="fri_primary_focus_8",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Timeline & Priorities",
            order=8,
            field_name="fri_primary_focus",
            text=(
                "What would you like us to focus on primarily:\n"
                "- Fact-finding (what happened and how),\n"
                "- Profiling the individuals involved,\n"
                "- Tracing money or assets,\n"
                "- Testing systems/controls to understand gaps,\n"
                "- Or a combination of these?"
            ),
            type="string",
            default_next="fri_constraints_9",
        ),

        "fri_constraints_9": QuestionStep(
            id="fri_constraints_9",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Timeline & Priorities",
            order=9,
            field_name="fri_constraints",
            text=(
                "Are there any constraints we must respect? For example:\n"
                "- No contact yet with certain people\n"
                "- Sensitive union/work council environment\n"
                "- Need to avoid alarming the suspect\n"
                "- Must not access certain data/systems"
            ),
            type="string",
            default_next="fri.confidentiality_requirements_10",
        ),

        "fri.confidentiality_requirements_10": QuestionStep(
            id="fri.confidentiality_requirements_10",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Budget & next steps",
            order=10,
            field_name="fri_confidentiality_requirements",
            text="Are there any special confidentiality or reporting requirements (who can be informed internally, how updates should be shared)?",
            type="string",
            default_next="fri.external_escalation_likelihood_11",
        ),

        "fri.external_escalation_likelihood_11": QuestionStep(
            id="fri.external_escalation_likelihood_11",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Budget & next steps",
            order=11,
            field_name="fri_external_escalation_likelihood",
            text="Do you expect this to remain an internal matter, or is there a strong chance it will go to police/court or regulators?",
            type="string",
            default_next="fri.suspected_value_12",
        ),

        "fri.suspected_value_12": QuestionStep(
            id="fri.suspected_value_12",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Investigation Parameter",
            order=12,
            field_name="fri_suspected_value",
            text="What is the approximate value of the suspected fraud or potential loss?",
            type="string",
            # default_next="fri.budget_range_13",
            default_next="fri.future_cases_14",
        ),

        # "fri.budget_range_13": QuestionStep(
        #     id="fri.budget_range_13",
        #     service_code="FRI",
        #     service_label="Fraud Investigation",
        #     section="Budget & next steps",
        #     order=13,
        #     field_name="fri_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on scope, countries and timelines?",
        #     type="string",
        #     default_next="fri.future_cases_14",
        # ),

        "fri.future_cases_14": QuestionStep(
            id="fri.future_cases_14",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Next Steps & Contact",
            order=14,
            field_name="fri_future_cases",
            text="Is this a one-off case, or do you foresee other similar matters where you may need investigation support in the future?",
            type="string",
            default_next="fri.client_company_profile_15",
        ),

        "fri.client_company_profile_15": QuestionStep(
            id="fri.client_company_profile_15",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Organization & role",
            order=15,
            field_name="fri_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="fri_user_role_16",
        ),

        "fri_user_role_16": QuestionStep(
            id="fri_user_role_16",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Organization & role",
            order=16,
            field_name="fri_user_role",
            text="What is your role in this matter? (HR, legal, internal audit, compliance, finance, management, external lawyer, owner, etc.)",
            type="string",
            default_next="fri.proposal_plan_request_17",
        ),

        "fri.proposal_plan_request_17": QuestionStep(
            id="fri.proposal_plan_request_17",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Next Steps & Contact",
            order=17,
            field_name="fri_proposal_plan_request",
            text="Would you like us to prepare a tailored proposal / investigation plan based on what you have shared?",
            type="string",
            # default_next="fri.contact_details_18",
            default_next="fri.investigation_timeline_19",
        ),

        # "fri.contact_details_18": QuestionStep(
        #     id="fri.contact_details_18",
        #     service_code="FRI",
        #     service_label="Fraud Investigation",
        #     section="Next Steps & Contact",
        #     order=18,
        #     field_name="fri_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, schedule a call?",
        #     type="string",
        #     default_next="fri.investigation_timeline_19",
        # ),

        "fri.investigation_timeline_19": QuestionStep(
            id="fri.investigation_timeline_19",
            service_code="FRI",
            service_label="Fraud Investigation",
            section="Timeline & Priorities",
            order=19,
            field_name="fri_investigation_timeline",
            text="What is your ideal timeline for the investigation? Are there any critical dates (e.g. board meeting, audit committee, disciplinary hearing, litigation deadline)?",
            type="string",
            default_next=None,  # selesai → completed
        ),
    }

def build_msy_flow() -> dict[str, QuestionStep]:
    return {
        "msy.geography_1": QuestionStep(
            id="msy.geography_1",
            service_code="MSY",
            service_label="Market Survey",
            section="Scope Specification",
            order=1,
            field_name="msy_geography",
            text="In which country or cities/regions do you want to conduct the survey?",
            type="string",
            default_next="msy.methods_2",
        ),

        "msy.methods_2": QuestionStep(
            id="msy.methods_2",
            service_code="MSY",
            service_label="Market Survey",
            section="Investigation Parameter",
            order=2,
            field_name="msy_methods",
            text=(
                "Which methods are you interested in:\n"
                "- Online surveys\n"
                "- Telephone interviews\n"
                "- Face-to-face interviews\n"
                "- Focus groups / in-depth interviews\n"
                "- A combination?"
            ),
            type="string",
            default_next="msy.b2b_b2c_3",
        ),

        "msy.b2b_b2c_3": QuestionStep(
            id="msy.b2b_b2c_3",
            service_code="MSY",
            service_label="Market Survey",
            section="Scope Specification",
            order=3,
            field_name="msy_b2b_b2c",
            text="Is this for B2C (consumers), B2B (businesses), or both?",
            type="string",
            default_next="msy.main_objective_4",
        ),

        "msy.main_objective_4": QuestionStep(
            id="msy.main_objective_4",
            service_code="MSY",
            service_label="Market Survey",
            section="Context Confirmation",
            order=4,
            field_name="msy_main_objective",
            text=(
                "What is the main objective of the survey? For example:\n"
                "- Understand customer needs or satisfaction\n"
                "- Test a new product or service concept\n"
                "- Measure brand awareness or perception\n"
                "- Assess a new market or geography\n"
                "- Understand competitors or pricing\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="msy.context_confirmation_5",
        ),

        "msy.context_confirmation_5": QuestionStep(
            id="msy.context_confirmation_5",
            service_code="MSY",
            service_label="Market Survey",
            section="Context Confirmation",
            order=5,
            field_name="msy_context_confirmation",
            text=(
                "Are you looking for a market survey / market research to better understand customers, competitors, or a specific market?"
            ),
            type="string",
            default_next="msy.respondent_volume_6",
        ),

        "msy.respondent_volume_6": QuestionStep(
            id="msy.respondent_volume_6",
            service_code="MSY",
            service_label="Market Survey",
            section="Investigation Parameter",
            order=6,
            field_name="msy_respondent_volume",
            text="Do you have a rough idea of the number of respondents you would like to reach (for example 100, 300, 500+)?",
            type="string",
            default_next="msy.fieldwork_timeline_7",
        ),

        "msy.fieldwork_timeline_7": QuestionStep(
            id="msy.fieldwork_timeline_7",
            service_code="MSY",
            service_label="Market Survey",
            section="Timeline & Priorities",
            order=7,
            field_name="msy_fieldwork_timeline",
            text="When would you like the fieldwork (data collection) to start, and by when do you need the final results?",
            type="string",
            # default_next="msy.budget_range_8",
            default_next="msy.survey_frequency_9",
        ),

        # "msy.budget_range_8": QuestionStep(
        #     id="msy.budget_range_8",
        #     service_code="MSY",
        #     service_label="Market Survey",
        #     section="Budget & next steps",
        #     order=8,
        #     field_name="msy_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on sample size, countries and methodology?",
        #     type="string",
        #     default_next="msy.survey_frequency_9",
        # ),

        "msy.survey_frequency_9": QuestionStep(
            id="msy.survey_frequency_9",
            service_code="MSY",
            service_label="Market Survey",
            section="Next Steps & Contact",
            order=9,
            field_name="msy_survey_frequency",
            text="Is this a one-time survey, or do you foresee regular surveys (e.g. yearly customer satisfaction, repeated waves)?",
            type="string",
            default_next="msy.deliverable_preference_10",
        ),

        "msy.deliverable_preference_10": QuestionStep(
            id="msy.deliverable_preference_10",
            service_code="MSY",
            service_label="Market Survey",
            section="Budget & next steps",
            order=10,
            field_name="msy_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- Raw data only\n"
                "- Summary of key findings\n"
                "- Full report with analysis, charts and recommendations\n"
                "- Presentation for management?"
            ),
            type="string",
            default_next="msy.questionnaire_readiness_11",
        ),

        "msy.questionnaire_readiness_11": QuestionStep(
            id="msy.questionnaire_readiness_11",
            service_code="MSY",
            service_label="Market Survey",
            section="Investigation Parameter",
            order=11,
            field_name="msy_questionnaire_readiness",
            text="Do you already have a questionnaire or key questions, or would you like us to design the questionnaire for you?",
            type="string",
            default_next="msy_target_audience_12",
        ),

        "msy_target_audience_12": QuestionStep(
            id="msy_target_audience_12",
            service_code="MSY",
            service_label="Market Survey",
            section="Scope Specification",
            order=12,
            field_name="msy_target_audience",
            text=(
                "Who do you want to survey? For example:\n"
                "- Existing customers\n"
                "- Potential customers / general public\n"
                "- Specific segments (e.g. age group, income level, profession)\n"
                "- Distributors, retailers, or partners"
            ),
            type="string",
            default_next="msy_client_company_profile_13",
        ),

        "msy_client_company_profile_13": QuestionStep(
            id="msy_client_company_profile_13",
            service_code="MSY",
            service_label="Market Survey",
            section="Organization & role",
            order=13,
            field_name="msy_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="msy_user_role_14",
        ),

        "msy_user_role_14": QuestionStep(
            id="msy_user_role_14",
            service_code="MSY",
            service_label="Market Survey",
            section="Organization & role",
            order=14,
            field_name="msy_user_role",
            text="What is your role in the company? (marketing, sales, management, product, strategy, other)",
            type="string",
            default_next="msy_proposal_summary_request_15",
        ),

        "msy_proposal_summary_request_15": QuestionStep(
            id="msy_proposal_summary_request_15",
            service_code="MSY",
            service_label="Market Survey",
            section="Next Steps & Contact",
            order=15,
            field_name="msy_proposal_summary_request",
            text="Would you like us to prepare a tailored proposal summarizing target audience, geography, methodology, and sample size options?",
            type="string",
            # default_next="msy_contact_details_16",
            default_next=None,  # selesai → completed
        ),

        # "msy_contact_details_16": QuestionStep(
        #     id="msy_contact_details_16",
        #     service_code="MSY",
        #     service_label="Market Survey",
        #     section="Next Steps & Contact",
        #     order=16,
        #     field_name="msy_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and follow up with you?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

from .sa_types import QuestionStep, Choice

def build_skt_flow() -> dict[str, QuestionStep]:
    return {
        "skt.possible_countries_1": QuestionStep(
            id="skt.possible_countries_1",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Scope Specification",
            order=1,
            field_name="skt_possible_countries",
            text="In which country or countries do you believe the person may currently be living, staying, or have strong connections?",
            type="string",
            default_next="skt.target_type_3",
        ),

        # "skt.context_confirmation_2": QuestionStep(
        #     id="skt.context_confirmation_2",
        #     service_code="SKT",
        #     service_label="Skip Tracing",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="skt_context_confirmation",
        #     text=(
        #         "Are you looking to skip tracing / locating a person whose current whereabouts are unknown?"
        #     ),
        #     type="string",
        #     default_next="skt.target_type_3",
        # ),

        "skt.target_type_3": QuestionStep(
            id="skt.target_type_3",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Scope Specification",
            order=3,
            field_name="skt_target_type",
            text="Who is the target of the skip tracing: an individual or a company representative?",
            type="string",
            default_next="skt.target_identity_and_relationship_4",
        ),

        "skt.target_identity_and_relationship_4": QuestionStep(
            id="skt.target_identity_and_relationship_4",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Scope Specification",
            order=4,
            field_name="skt_target_identity_and_relationship",
            text="What is the name of the person (and company, if relevant), and what is your relationship with them (debtor, ex-employee, client, vendor, other)?",
            type="string",
            default_next="skt.available_information_5",
        ),

        "skt.available_information_5": QuestionStep(
            id="skt.available_information_5",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Timeline & Priorities",
            order=5,
            field_name="skt_available_information",
            text=(
                "Which information do you already have about this person? For example:\n"
                "- Full name (and any aliases)\n"
                "- Date of birth / ID number\n"
                "- Last known address\n"
                "- Phone numbers / email addresses\n"
                "- Employer or business links\n"
                "- Social media profiles, vehicle, or other details"
            ),
            type="string",
            default_next="skt.previous_attempts_6",
        ),

        "skt.previous_attempts_6": QuestionStep(
            id="skt.previous_attempts_6",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Investigation Parameter",
            order=6,
            field_name="skt_previous_attempts",
            text="Have you already tried to contact or locate this person? If yes, what has been done so far?",
            type="string",
            default_next="skt.main_objective_7",
        ),

        "skt.main_objective_7": QuestionStep(
            id="skt.main_objective_7",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Context Confirmation",
            order=7,
            field_name="skt_main_objective",
            text=(
                "What is the main objective of locating this person? For example:\n"
                "- Debt recovery / unpaid obligations\n"
                "- Service of legal documents (summons, court papers)\n"
                "- Enforcement of a judgment or arbitration\n"
                "- Locating a former employee / partner / shareholder\n"
                "- Locating a witness or key person in an investigation\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="skt.legal_stage_8",
        ),

        "skt.legal_stage_8": QuestionStep(
            id="skt.legal_stage_8",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Investigation Parameter",
            order=8,
            field_name="skt_legal_stage",
            text="Have you started any legal action (or do you plan to), or is this still at a pre-legal / pre-collection stage?",
            type="string",
            default_next="skt.client_company_profile_9",
        ),

        "skt.client_company_profile_9": QuestionStep(
            id="skt.client_company_profile_9",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Organization & role",
            order=9,
            field_name="skt_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="skt.user_role_10",
        ),

        "skt.user_role_10": QuestionStep(
            id="skt.user_role_10",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Organization & role",
            order=10,
            field_name="skt_user_role",
            text="What is your role in this matter? (credit/collection, legal, internal audit, risk, external lawyer, owner, other)",
            type="string",
            default_next="skt.proposal_request_11",
        ),

        "skt.proposal_request_11": QuestionStep(
            id="skt.proposal_request_11",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Next Steps & Contact",
            order=11,
            field_name="skt_proposal_request",
            text="Would you like us to prepare a tailored proposal based on your objective, available information and geography?",
            type="string",
            # default_next="skt.contact_details_12",
            default_next="skt.amount_at_stake_13",
        ),

        # "skt.contact_details_12": QuestionStep(
        #     id="skt.contact_details_12",
        #     service_code="SKT",
        #     service_label="Skip Tracing",
        #     section="Next Steps & Contact",
        #     order=12,
        #     field_name="skt_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, schedule a call?",
        #     type="string",
        #     default_next="skt.amount_at_stake_13",
        # ),

        "skt.amount_at_stake_13": QuestionStep(
            id="skt.amount_at_stake_13",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Investigation Parameter",
            order=13,
            field_name="skt_amount_at_stake",
            text="What is the approximate amount at stake or importance of the case (financial or strategic)?",
            type="string",
            default_next="skt.future_cases_14",
        ),

        "skt.future_cases_14": QuestionStep(
            id="skt.future_cases_14",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Next Steps & Contact",
            order=14,
            field_name="skt_future_cases",
            text="Is this a one-time case, or do you expect similar skip tracing needs in the future (e.g. portfolio of debtors or frequent cases)?",
            type="string",
            default_next="skt.deliverable_preference_15",
        ),

        "skt.deliverable_preference_15": QuestionStep(
            id="skt.deliverable_preference_15",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Budget & next steps",
            order=15,
            field_name="skt_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- A simple confirmation of current address/contact details, or\n"
                "- A short report outlining findings, sources and recommendations for next steps?"
            ),
            type="string",
            default_next="skt.timeline_expectation_16",
        ),

        "skt.timeline_expectation_16": QuestionStep(
            id="skt.timeline_expectation_16",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Timeline & Priorities",
            order=16,
            field_name="skt_timeline_expectation",
            text="What is your ideal timeline for obtaining updated contact or location information? Is it linked to any legal or internal deadline?",
            type="string",
            default_next="skt.constraints_17",
        ),

        "skt.constraints_17": QuestionStep(
            id="skt.constraints_17",
            service_code="SKT",
            service_label="Skip Tracing",
            section="Timeline & Priorities",
            order=17,
            field_name="skt_constraints",
            text=(
                "Are there any constraints we must respect? For example:\n"
                "- No direct contact with the person\n"
                "- Do not contact family/employer\n"
                "- Need to avoid alerting the person\n"
                "- Must stay strictly within a specific jurisdiction"
            ),
            type="string",
            # default_next="skt.budget_range_18",
            default_next=None,  # selesai → completed
        ),

        # "skt.budget_range_18": QuestionStep(
        #     id="skt.budget_range_18",
        #     service_code="SKT",
        #     service_label="Skip Tracing",
        #     section="Budget & next steps",
        #     order=18,
        #     field_name="skt_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on countries, information available and timelines?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_cmi_flow() -> dict[str, QuestionStep]:
    return {
        "cmi.countries_1": QuestionStep(
            id="cmi.countries_1",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Scope Specification",
            order=1,
            field_name="cmi_countries",
            text="In which country or countries do you need us to investigate the use of this trademark or brand?",
            type="string",
            default_next="cmi.main_objective_3",
        ),

        # "cmi.context_confirmation_2": QuestionStep(
        #     id="cmi.context_confirmation_2",
        #     service_code="CMI",
        #     service_label="Trademark Investigation",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="cmi_context_confirmation",
        #     text=(
        #         "Are you looking for a trademark / brand investigation related to possible misuse, infringement, or counterfeiting of your brand?"
        #     ),
        #     type="string",
        #     default_next="cmi.main_objective_3",
        # ),

        "cmi.main_objective_3": QuestionStep(
            id="cmi.main_objective_3",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Context Confirmation",
            order=3,
            field_name="cmi_main_objective",
            text=(
                "What is the main objective of the trademark investigation? For example:\n"
                "- Check if a mark is being used in the market (use investigation)\n"
                "- Confirm infringement or counterfeiting\n"
                "- Identify the source / supply chain of infringing goods\n"
                "- Support enforcement actions (police, customs, civil action)\n"
                "- Monitor distributors / licensees / ex-partners\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="cmi.concerned_situation_4",
        ),

        "cmi.concerned_situation_4": QuestionStep(
            id="cmi.concerned_situation_4",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Investigation Parameter",
            order=4,
            field_name="cmi_concerned_situation",
            text=(
                "What is the situation you are concerned about? For example:\n"
                "- Copycat products or packaging\n"
                "- Similar brand name / logo used by another company\n"
                "- Former distributor or licensee still using the brand\n"
                "- Online sellers using the mark without authorization\n"
                "- Parallel imports / grey market"
            ),
            type="string",
            default_next="cmi.where_seen_5",
        ),

        "cmi.where_seen_5": QuestionStep(
            id="cmi.where_seen_5",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Investigation Parameter",
            order=5,
            field_name="cmi_where_seen",
            text="Where have you seen this use or infringement so far? (e.g. specific cities, markets, shops, online platforms/marketplaces, social media)",
            type="string",
            default_next="cmi.evidence_or_samples_6",
        ),

        "cmi.evidence_or_samples_6": QuestionStep(
            id="cmi.evidence_or_samples_6",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Investigation Parameter",
            order=6,
            field_name="cmi_evidence_or_samples",
            text="Do you already have any evidence or samples (photos, URLs, invoices, screenshots) that you can share?",
            type="string",
            default_next="cmi.primary_focus_7",
        ),

        "cmi.primary_focus_7": QuestionStep(
            id="cmi.primary_focus_7",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Timeline & Priorities",
            order=7,
            field_name="cmi_primary_focus",
            text=(
                "What would you like us to focus on primarily:\n"
                "- Confirming use in commerce (use investigation),\n"
                "- Identifying the scale and locations of infringement,\n"
                "- Finding the source / manufacturer / importer,\n"
                "- Preparing for enforcement / litigation,\n"
                "- Or a combination of these?"
            ),
            type="string",
            default_next="cmi.owner_or_representative_8",
        ),

        "cmi.owner_or_representative_8": QuestionStep(
            id="cmi.owner_or_representative_8",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Scope Specification",
            order=8,
            field_name="cmi_owner_or_representative",
            text="Are you the owner of the mark, or acting on behalf of the owner (e.g. as lawyer or licensee)?",
            type="string",
            default_next="cmi.registration_status_9",
        ),

        "cmi.registration_status_9": QuestionStep(
            id="cmi.registration_status_9",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Scope Specification",
            order=9,
            field_name="cmi_registration_status",
            text="Is the mark registered in those countries, or is it still pending / unregistered?",
            type="string",
            default_next="cmi.brand_or_trademark_10",
        ),

        "cmi.brand_or_trademark_10": QuestionStep(
            id="cmi.brand_or_trademark_10",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Scope Specification",
            order=10,
            field_name="cmi_brand_or_trademark",
            text="Which trademark or brand is concerned? (word mark, logo, or both – please specify the name)",
            type="string",
            default_next="cmi.constraints_working_method_11",
        ),

        "cmi.constraints_working_method_11": QuestionStep(
            id="cmi.constraints_working_method_11",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Timeline & Priorities",
            order=11,
            field_name="cmi_constraints_working_method",
            text=(
                "Are there any constraints on how we work? For example:\n"
                "- Need to remain strictly discreet / undercover\n"
                "- Limits on test purchases or sample collection\n"
                "- Restrictions on contacting certain parties"
            ),
            type="string",
            default_next="cmi.future_monitoring_12",
        ),

        "cmi.future_monitoring_12": QuestionStep(
            id="cmi.future_monitoring_12",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Next Steps & Contact",
            order=12,
            field_name="cmi_future_monitoring",
            text="Is this a one-time investigation, or do you expect ongoing brand monitoring or repeated actions in this market?",
            type="string",
            default_next="cmi.timeline_13",
        ),

        "cmi.timeline_13": QuestionStep(
            id="cmi.timeline_13",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Timeline & Priorities",
            order=13,
            field_name="cmi_timeline",
            text="What is your ideal timeline for this investigation? Is it linked to any deadline (e.g. hearing, opposition, enforcement action, internal decision)?",
            type="string",
            default_next="cmi.deliverable_preference_14",
        ),

        "cmi.deliverable_preference_14": QuestionStep(
            id="cmi.deliverable_preference_14",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Budget & next steps",
            order=14,
            field_name="cmi_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- A short findings summary (with photos/URLs),\n"
                "- A detailed report with investigation steps and evidence,\n"
                "- Or both?"
            ),
            type="string",
            # default_next="cmi.budget_range_15",
            default_next="cmi.client_company_profile_16",
        ),

        # "cmi.budget_range_15": QuestionStep(
        #     id="cmi.budget_range_15",
        #     service_code="CMI",
        #     service_label="Trademark Investigation",
        #     section="Budget & next steps",
        #     order=15,
        #     field_name="cmi_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on countries, scope and methods?",
        #     type="string",
        #     default_next="cmi.client_company_profile_16",
        # ),

        "cmi.client_company_profile_16": QuestionStep(
            id="cmi.client_company_profile_16",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Organization & role",
            order=16,
            field_name="cmi_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="cmi.user_role_17",
        ),

        "cmi.user_role_17": QuestionStep(
            id="cmi.user_role_17",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Organization & role",
            order=17,
            field_name="cmi_user_role",
            text="What is your role in this matter? (brand owner, in-house legal, IP manager, external lawyer, distributor, other)",
            type="string",
            default_next="cmi.proposal_request_18",
        ),

        "cmi.proposal_request_18": QuestionStep(
            id="cmi.proposal_request_18",
            service_code="CMI",
            service_label="Trademark Investigation",
            section="Next Steps & Contact",
            order=18,
            field_name="cmi_proposal_request",
            text="Would you like us to prepare a tailored proposal based on the trademark, countries and scope you described?",
            type="string",
            # default_next="cmi.contact_details_19",
            default_next=None,  # selesai → completed
        ),

        # "cmi.contact_details_19": QuestionStep(
        #     id="cmi.contact_details_19",
        #     service_code="CMI",
        #     service_label="Trademark Investigation",
        #     section="Next Steps & Contact",
        #     order=19,
        #     field_name="cmi_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, schedule a call?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_nui_flow() -> dict[str, QuestionStep]:
    return {
        "nui.countries_1": QuestionStep(
            id="nui.countries_1",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Scope Specification",
            order=1,
            field_name="nui_countries",
            text="In which country or countries do you need us to check use or non-use of the trademark?",
            type="string",
            default_next="nui.main_objective_3",
        ),

        # "nui.context_confirmation_2": QuestionStep(
        #     id="nui.context_confirmation_2",
        #     service_code="NUI",
        #     service_label="Non-Use Investigation",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="nui_context_confirmation",
        #     text=(
        #         "Are you looking for a trademark non-use / use investigation to check whether a mark is actually being used in the market?"
        #     ),
        #     type="string",
        #     default_next="nui.main_objective_3",
        # ),

        "nui.main_objective_3": QuestionStep(
            id="nui.main_objective_3",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Context Confirmation",
            order=3,
            field_name="nui_main_objective",
            text=(
                "What is the main objective of this non-use investigation? For example:\n"
                "- Prepare or support a non-use cancellation action\n"
                "- Defend against a non-use attack on your own mark\n"
                "- Assess whether a third-party mark is really used before taking action\n"
                "- Support a dispute, opposition or negotiation\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="nui.mark_owner_4",
        ),

        "nui.mark_owner_4": QuestionStep(
            id="nui.mark_owner_4",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Scope Specification",
            order=4,
            field_name="nui_mark_owner",
            text="Who is the owner of this mark (you / your client / a third party)?",
            type="string",
            default_next="nui.known_use_context_5",
        ),

        "nui.known_use_context_5": QuestionStep(
            id="nui.known_use_context_5",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Investigation Parameter",
            order=5,
            field_name="nui_known_use_context",
            text=(
                "What do you already know about possible use of the mark? For example:\n"
                "- You suspect no use at all\n"
                "- You believe it might be used only in a limited way\n"
                "- You have seen some products, shops or websites but are unsure if it is genuine / sufficient use"
            ),
            type="string",
            default_next="nui.evidence_or_indications_6",
        ),

        "nui.evidence_or_indications_6": QuestionStep(
            id="nui.evidence_or_indications_6",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Investigation Parameter",
            order=6,
            field_name="nui_evidence_or_indications",
            text="Do you already have any evidence or indications (photos, URLs, invoices, packaging, screenshots, registry extracts) that you can share?",
            type="string",
            default_next="nui.primary_focus_7",
        ),

        "nui.primary_focus_7": QuestionStep(
            id="nui.primary_focus_7",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Timeline & Priorities",
            order=7,
            field_name="nui_primary_focus",
            text=(
                "What would you like us to focus on primarily:\n"
                "- Confirming that there is no use of the mark\n"
                "- Checking whether any use is genuine and in line with registrations\n"
                "- Identifying where and how the mark is used (channels, products, territory)\n"
                "- Preparing evidence for proceedings (e.g. cancellation, opposition, litigation)\n"
                "- Or a combination of these?"
            ),
            type="string",
            default_next="nui.field_checks_preference_8",
        ),

        "nui.field_checks_preference_8": QuestionStep(
            id="nui.field_checks_preference_8",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Investigation Parameter",
            order=8,
            field_name="nui_field_checks_preference",
            text="Are you comfortable with field checks (visits to shops/marketplaces), or should the investigation be limited to online and documentary research only?",
            type="string",
            default_next="nui.timeline_9",
        ),

        "nui.timeline_9": QuestionStep(
            id="nui.timeline_9",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Timeline & Priorities",
            order=9,
            field_name="nui_timeline",
            text="What is your ideal timeline for this non-use investigation? Is it linked to any procedural deadline (e.g. filing / responding in a cancellation, opposition, or court case)?",
            type="string",
            default_next="nui.constraints_working_method_10",
        ),

        "nui.constraints_working_method_10": QuestionStep(
            id="nui.constraints_working_method_10",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Timeline & Priorities",
            order=10,
            field_name="nui_constraints_working_method",
            text=(
                "Are there any constraints on how we work? For example:\n"
                "- Need to remain strictly discreet / undercover\n"
                "- No direct contact with certain parties\n"
                "- No test purchases\n"
                "- Coordination with a local attorney"
            ),
            type="string",
            default_next="nui.brand_or_trademark_11",
        ),

        "nui.brand_or_trademark_11": QuestionStep(
            id="nui.brand_or_trademark_11",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Scope Specification",
            order=11,
            field_name="nui_brand_or_trademark",
            text="Which trademark or brand is concerned? (word mark, logo, or both – please specify the name)",
            type="string",
            default_next="nui.registration_status_12",
        ),

        "nui.registration_status_12": QuestionStep(
            id="nui.registration_status_12",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Scope Specification",
            order=12,
            field_name="nui_registration_status",
            text="Is the mark registered in those countries, or still pending / unregistered?",
            type="string",
            default_next="nui.relevant_period_13",
        ),

        "nui.relevant_period_13": QuestionStep(
            id="nui.relevant_period_13",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Investigation Parameter",
            order=13,
            field_name="nui_relevant_period",
            text="For which period of time is use or non-use relevant? (for example, the last 3–5 years or another specific period required by law/procedure)",
            type="string",
            default_next="nui.client_company_profile_14",
        ),

        "nui.client_company_profile_14": QuestionStep(
            id="nui.client_company_profile_14",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Organization & role",
            order=14,
            field_name="nui_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="nui.user_role_15",
        ),

        "nui.user_role_15": QuestionStep(
            id="nui.user_role_15",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Organization & role",
            order=15,
            field_name="nui_user_role",
            text="What is your role in this matter? (brand owner, in-house legal, IP manager, external lawyer, licensee, other)",
            type="string",
            default_next="nui.deliverable_preference_16",
        ),

        "nui.deliverable_preference_16": QuestionStep(
            id="nui.deliverable_preference_16",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Budget & next steps",
            order=16,
            field_name="nui_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- A short findings summary (use vs non-use, with key evidence),\n"
                "- A full report with detailed findings, photos/URLs and analysis,\n"
                "- Or both?"
            ),
            type="string",
            # default_next="nui.budget_range_17",
            default_next="nui.future_portfolio_18",
        ),

        # "nui.budget_range_17": QuestionStep(
        #     id="nui.budget_range_17",
        #     service_code="NUI",
        #     service_label="Non-Use Investigation",
        #     section="Budget & next steps",
        #     order=17,
        #     field_name="nui_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on countries, scope and methods?",
        #     type="string",
        #     default_next="nui.future_portfolio_18",
        # ),

        "nui.future_portfolio_18": QuestionStep(
            id="nui.future_portfolio_18",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Next Steps & Contact",
            order=18,
            field_name="nui_future_portfolio",
            text="Is this a one-off investigation, or do you expect other non-use / use investigations for your portfolio in the future?",
            type="string",
            default_next="nui.proposal_request_19",
        ),

        "nui.proposal_request_19": QuestionStep(
            id="nui.proposal_request_19",
            service_code="NUI",
            service_label="Non-Use Investigation",
            section="Next Steps & Contact",
            order=19,
            field_name="nui_proposal_request",
            text="Would you like us to prepare a tailored proposal based on the trademark, countries and objectives you described?",
            type="string",
            # default_next="nui.contact_details_20",
            default_next=None,  # selesai → completed
        ),

        # "nui.contact_details_20": QuestionStep(
        #     id="nui.contact_details_20",
        #     service_code="NUI",
        #     service_label="Non-Use Investigation",
        #     section="Next Steps & Contact",
        #     order=20,
        #     field_name="nui_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, coordinate with you or your IP counsel?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_aci_flow() -> dict[str, QuestionStep]:
    return {
        "aci.geography_1": QuestionStep(
            id="aci.geography_1",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Scope Specification",
            order=1,
            field_name="aci_geography",
            text="In which country or cities/regions do you need us to focus the anti-counterfeiting work?",
            type="string",
            default_next="aci.main_objective_3",
        ),

        # "aci.context_confirmation_2": QuestionStep(
        #     id="aci.context_confirmation_2",
        #     service_code="ACI",
        #     service_label="Anti-Counterfeiting",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="aci_context_confirmation",
        #     text=(
        #         "Are you looking for support with anti-counterfeiting / brand protection related to fake or unauthorized products using your brand?"
        #     ),
        #     type="string",
        #     default_next="aci.main_objective_3",
        # ),

        "aci.main_objective_3": QuestionStep(
            id="aci.main_objective_3",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Context Confirmation",
            order=3,
            field_name="aci_main_objective",
            text=(
                "What is the main objective of this project? For example:\n"
                "- Identify where counterfeit products are being sold\n"
                "- Map the supply chain (manufacturers, importers, distributors)\n"
                "- Support enforcement actions (police raids, customs, civil actions)\n"
                "- Monitor licensees / distributors for misuse\n"
                "- Prepare evidence for legal proceedings\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="aci.hotspot_scope_4",
        ),

        "aci.hotspot_scope_4": QuestionStep(
            id="aci.hotspot_scope_4",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Scope Specification",
            order=4,
            field_name="aci_hotspot_scope",
            text="Do you want to cover specific hotspots (e.g. certain markets/areas) or a broader mapping of the country/region?",
            type="string",
            default_next="aci.current_situation_5",
        ),

        "aci.current_situation_5": QuestionStep(
            id="aci.current_situation_5",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Investigation Parameter",
            order=5,
            field_name="aci_current_situation",
            text=(
                "What is the situation you are seeing today? For example:\n"
                "- Counterfeits in traditional markets/shops\n"
                "- Online sales (marketplaces, social media, websites)\n"
                "- Suspected factories/warehouses\n"
                "- Former partners still using your brand\n"
                "- Parallel imports / grey market"
            ),
            type="string",
            default_next="aci.where_found_6",
        ),

        "aci.where_found_6": QuestionStep(
            id="aci.where_found_6",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Investigation Parameter",
            order=6,
            field_name="aci_where_found",
            text="Where have you seen or found these products so far? (cities, markets, shops, websites, platforms, links)",
            type="string",
            default_next="aci.evidence_or_samples_7",
        ),

        "aci.evidence_or_samples_7": QuestionStep(
            id="aci.evidence_or_samples_7",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Investigation Parameter",
            order=7,
            field_name="aci_evidence_or_samples",
            text="Do you already have any evidence or samples (photos, product samples, packaging, URLs, screenshots, invoices) that you can share?",
            type="string",
            default_next="aci.primary_focus_8",
        ),

        "aci.primary_focus_8": QuestionStep(
            id="aci.primary_focus_8",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Timeline & Priorities",
            order=8,
            field_name="aci_primary_focus",
            text=(
                "What would you like us to focus on primarily:\n"
                "- Market sweeps / sample purchases\n"
                "- Identifying key sellers and hotspots\n"
                "- Tracing back to distributors or importers\n"
                "- Identifying manufacturing / storage locations\n"
                "- Supporting raids and legal enforcement\n"
                "- Or a combination of these?"
            ),
            type="string",
            default_next="aci.constraints_9",
        ),

        "aci.constraints_9": QuestionStep(
            id="aci.constraints_9",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Timeline & Priorities",
            order=9,
            field_name="aci_constraints",
            text=(
                "Are there any constraints on our approach? For example:\n"
                "- Need to remain fully undercover\n"
                "- No direct contact with certain parties\n"
                "- Limits on test purchases or amount to be spent\n"
                "- Internal approval needed before approaching authorities"
            ),
            type="string",
            default_next="aci.coordination_preference_10",
        ),

        "aci.coordination_preference_10": QuestionStep(
            id="aci.coordination_preference_10",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Budget & next steps",
            order=10,
            field_name="aci_coordination_preference",
            text="Are you already working with law firms, authorities or customs on this matter, or would you like us to coordinate with them or recommend partners?",
            type="string",
            default_next="aci.brand_and_products_11",
        ),

        "aci.brand_and_products_11": QuestionStep(
            id="aci.brand_and_products_11",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Scope Specification",
            order=11,
            field_name="aci_brand_and_products",
            text="Which brand/trademark and products are concerned? (e.g. brand name, product category: electronics, fashion, FMCG, pharma, etc.)",
            type="string",
            default_next="aci.client_company_profile_12",
        ),

        "aci.client_company_profile_12": QuestionStep(
            id="aci.client_company_profile_12",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Organization & role",
            order=12,
            field_name="aci_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="aci.user_role_13",
        ),

        "aci.user_role_13": QuestionStep(
            id="aci.user_role_13",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Organization & role",
            order=13,
            field_name="aci_user_role",
            text="What is your role in this matter? (brand owner, in-house legal/IP, external lawyer, regional manager, licensee/distributor, other)",
            type="string",
            default_next="aci.timeline_14",
        ),

        "aci.timeline_14": QuestionStep(
            id="aci.timeline_14",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Timeline & Priorities",
            order=14,
            field_name="aci_timeline",
            text="What is your ideal timeline for this anti-counterfeiting project? Is it linked to any specific deadline (e.g. planned raids, court dates, internal reporting)?",
            type="string",
            default_next="aci.deliverable_preference_15",
        ),

        "aci.deliverable_preference_15": QuestionStep(
            id="aci.deliverable_preference_15",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Budget & next steps",
            order=15,
            field_name="aci_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- A mapping report of sellers/locations\n"
                "- A detailed investigation report with evidence and recommendations\n"
                "- Operational raid/enforcement support plus reports\n"
                "- Or a combination?"
            ),
            type="string",
            # default_next="aci.budget_range_16",
            default_next="aci.future_program_17",
        ),

        # "aci.budget_range_16": QuestionStep(
        #     id="aci.budget_range_16",
        #     service_code="ACI",
        #     service_label="Anti-Counterfeiting",
        #     section="Budget & next steps",
        #     order=16,
        #     field_name="aci_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on geography, scope and methods?",
        #     type="string",
        #     default_next="aci.future_program_17",
        # ),

        "aci.future_program_17": QuestionStep(
            id="aci.future_program_17",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Next Steps & Contact",
            order=17,
            field_name="aci_future_program",
            text="Is this a one-off action (e.g. a campaign) or do you foresee ongoing brand protection work in this market?",
            type="string",
            default_next="aci.proposal_request_18",
        ),

        "aci.proposal_request_18": QuestionStep(
            id="aci.proposal_request_18",
            service_code="ACI",
            service_label="Anti-Counterfeiting",
            section="Next Steps & Contact",
            order=18,
            field_name="aci_proposal_request",
            text="Would you like us to prepare a tailored proposal summarizing scope (brands, products, geography, methods) and possible phases?",
            type="string",
            # default_next="aci.contact_details_19",
            default_next=None,  # selesai → completed
        ),

        # "aci.contact_details_19": QuestionStep(
        #     id="aci.contact_details_19",
        #     service_code="ACI",
        #     service_label="Anti-Counterfeiting",
        #     section="Next Steps & Contact",
        #     order=19,
        #     field_name="aci_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, schedule a call?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_pti_flow() -> dict[str, QuestionStep]:
    return {
        "pti.affected_countries_1": QuestionStep(
            id="pti.affected_countries_1",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Scope Specification",
            order=1,
            field_name="pti_affected_countries",
            text="In which country or countries / regions are you seeing unauthorized or parallel sales of your products?",
            type="string",
            default_next="pti.main_objective_3",
        ),

        # "pti.context_confirmation_2": QuestionStep(
        #     id="pti.context_confirmation_2",
        #     service_code="PTI",
        #     service_label="Parallel Trading Investigation",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="pti_context_confirmation",
        #     text=(
        #         "Are you looking for support with a parallel trading / grey market investigation involving genuine products sold outside your official channels?"
        #     ),
        #     type="string",
        #     default_next="pti.main_objective_3",
        # ),

        "pti.main_objective_3": QuestionStep(
            id="pti.main_objective_3",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Context Confirmation",
            order=3,
            field_name="pti_main_objective",
            text=(
                "What is the main objective of this investigation? For example:\n"
                "- Identify who is importing/exporting outside your official channels\n"
                "- Map unofficial distributors / resellers\n"
                "- Understand the routes and sources of parallel imports/exports\n"
                "- Collect evidence to enforce contracts or distribution agreements\n"
                "- Support pricing / channel strategy decisions\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="pti.official_channel_setup_4",
        ),

        "pti.official_channel_setup_4": QuestionStep(
            id="pti.official_channel_setup_4",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Scope Specification",
            order=4,
            field_name="pti_official_channel_setup",
            text="What is your official channel setup there? (e.g. exclusive distributor, own subsidiary, multiple authorized distributors)",
            type="string",
            default_next="pti.suspicion_basis_5",
        ),

        "pti.suspicion_basis_5": QuestionStep(
            id="pti.suspicion_basis_5",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Investigation Parameter",
            order=5,
            field_name="pti_suspicion_basis",
            text=(
                "What makes you believe there is a parallel trading / grey market? For example:\n"
                "- Products found outside official distributors network\n"
                "- Unusual price undercutting\n"
                "- Products with foreign labels / packaging / batch codes\n"
                "- Complaints from official distributors\n"
                "- Internal sales data vs market presence mismatch"
            ),
            type="string",
            default_next="pti.where_detected_6",
        ),

        "pti.where_detected_6": QuestionStep(
            id="pti.where_detected_6",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Investigation Parameter",
            order=6,
            field_name="pti_where_detected",
            text="Where have you seen or detected these products so far? (specific cities, shops, markets, online platforms, distributors, countries of origin)",
            type="string",
            default_next="pti.suspected_routes_7",
        ),

        "pti.suspected_routes_7": QuestionStep(
            id="pti.suspected_routes_7",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Investigation Parameter",
            order=7,
            field_name="pti_suspected_routes",
            text="Which countries or trade routes do you suspect are involved? (for example, goods entering from neighboring countries or specific hubs)",
            type="string",
            default_next="pti.primary_focus_8",
        ),

        "pti.primary_focus_8": QuestionStep(
            id="pti.primary_focus_8",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Timeline & Priorities",
            order=8,
            field_name="pti_primary_focus",
            text=(
                "What would you like us to focus on primarily:\n"
                "- Identifying who is supplying the parallel products locally\n"
                "- Tracing back where the goods are coming from (source markets/countries)\n"
                "- Mapping the distribution chain (importer → wholesaler → retailer)\n"
                "- Testing authorized distributors for possible leakage\n"
                "- Gathering contractual/operational evidence for enforcement\n"
                "- Or a combination of these?"
            ),
            type="string",
            default_next="pti.constraints_9",
        ),

        "pti.constraints_9": QuestionStep(
            id="pti.constraints_9",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Timeline & Priorities",
            order=9,
            field_name="pti_constraints",
            text=(
                "Are there any constraints on our approach? For example:\n"
                "- Need to remain undercover and not be linked to the brand owner\n"
                "- No direct contact with certain distributors or partners\n"
                "- Limits on test purchases or sample values\n"
                "- Coordination with a specific law firm or HQ team"
            ),
            type="string",
            default_next="pti.evidence_or_samples_10",
        ),

        "pti.evidence_or_samples_10": QuestionStep(
            id="pti.evidence_or_samples_10",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Budget & next steps",
            order=10,
            field_name="pti_evidence_or_samples",
            text="Do you already have any evidence or samples (photos, invoices, packing lists, batch codes, screenshots, serial numbers) that you can share?",
            type="string",
            default_next="pti.timeline_11",
        ),

        "pti.timeline_11": QuestionStep(
            id="pti.timeline_11",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Timeline & Priorities",
            order=11,
            field_name="pti_timeline",
            text="What is your ideal timeline for this investigation? Is it linked to any contract renewal, pricing review, or legal deadline?",
            type="string",
            default_next="pti.client_company_profile_12",
        ),

        "pti.client_company_profile_12": QuestionStep(
            id="pti.client_company_profile_12",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Organization & role",
            order=12,
            field_name="pti_client_company_profile",
            text="Can you briefly describe your company and industry, and where your HQ is based?",
            type="string",
            default_next="pti.user_role_13",
        ),

        "pti.user_role_13": QuestionStep(
            id="pti.user_role_13",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Organization & role",
            order=13,
            field_name="pti_user_role",
            text="What is your role in this matter? (regional manager, sales, distribution, legal, compliance, brand protection, external lawyer, other)",
            type="string",
            default_next="pti.brands_and_products_14",
        ),

        "pti.brands_and_products_14": QuestionStep(
            id="pti.brands_and_products_14",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Scope Specification",
            order=14,
            field_name="pti_brands_and_products",
            text="Which brand(s) and products are affected by parallel trading?",
            type="string",
            default_next="pti.deliverable_preference_15",
        ),

        "pti.deliverable_preference_15": QuestionStep(
            id="pti.deliverable_preference_15",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Budget & next steps",
            order=15,
            field_name="pti_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- A mapping report of actors, locations, and routes\n"
                "- A detailed investigation report with evidence for enforcement\n"
                "- A summary for management with recommendations\n"
                "- Or a combination of these?"
            ),
            type="string",
            # default_next="pti.budget_range_16",
            default_next="pti.future_monitoring_17",
        ),

        # "pti.budget_range_16": QuestionStep(
        #     id="pti.budget_range_16",
        #     service_code="PTI",
        #     service_label="Parallel Trading Investigation",
        #     section="Budget & next steps",
        #     order=16,
        #     field_name="pti_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on countries, scope and depth of investigation?",
        #     type="string",
        #     default_next="pti.future_monitoring_17",
        # ),

        "pti.future_monitoring_17": QuestionStep(
            id="pti.future_monitoring_17",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Next Steps & Contact",
            order=17,
            field_name="pti_future_monitoring",
            text="Is this a one-off investigation for a specific issue, or do you anticipate ongoing parallel trading monitoring in this or other markets?",
            type="string",
            default_next="pti.proposal_request_18",
        ),

        "pti.proposal_request_18": QuestionStep(
            id="pti.proposal_request_18",
            service_code="PTI",
            service_label="Parallel Trading Investigation",
            section="Next Steps & Contact",
            order=18,
            field_name="pti_proposal_request",
            text="Would you like us to prepare a tailored proposal summarizing brands, products, geography, and investigation scope?",
            type="string",
            # default_next="pti.contact_details_19",
            default_next=None,  # selesai → completed
        ),

        # "pti.contact_details_19": QuestionStep(
        #     id="pti.contact_details_19",
        #     service_code="PTI",
        #     service_label="Parallel Trading Investigation",
        #     section="Next Steps & Contact",
        #     order=19,
        #     field_name="pti_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, schedule a call?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_abms_flow() -> dict[str, QuestionStep]:
    return {
        "abms.participants_and_countries_1": QuestionStep(
            id="abms.participants_and_countries_1",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Scope Specification",
            order=1,
            field_name="abms_participants_and_countries",
            text="Approximately how many participants do you expect, and in which country or countries are they located?",
            type="string",
            default_next="abms.entity_coverage_3",
        ),

        # "abms.context_confirmation_2": QuestionStep(
        #     id="abms.context_confirmation_2",
        #     service_code="ABMS",
        #     service_label="ABMS E-Learning",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="abms_context_confirmation",
        #     text=(
        #         "Are you looking for an Anti-Bribery Management System (ABMS) / anti-corruption e-learning for your organization?"
        #     ),
        #     type="string",
        #     default_next="abms.entity_coverage_3",
        # ),

        "abms.entity_coverage_3": QuestionStep(
            id="abms.entity_coverage_3",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Scope Specification",
            order=3,
            field_name="abms_entity_coverage",
            text="Do you need the training for one entity only, or for several entities / countries within your group?",
            type="string",
            default_next="abms.main_objective_4",
        ),

        "abms.main_objective_4": QuestionStep(
            id="abms.main_objective_4",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Context Confirmation",
            order=4,
            field_name="abms_main_objective",
            text=(
                "What is the main objective of the ABMS e-learning? For example:\n"
                "- General awareness for all employees\n"
                "- Training for higher-risk staff (sales, procurement, etc.)\n"
                "- Compliance with ISO 37001 or internal ABMS policy\n"
                "- Support for certification / audit\n"
                "- Refresher training after incidents or audits\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="abms.training_audience_5",
        ),

        "abms.training_audience_5": QuestionStep(
            id="abms.training_audience_5",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Scope Specification",
            order=5,
            field_name="abms_training_audience",
            text=(
                "Who do you want to train with this e-learning? For example:\n"
                "- All employees\n"
                "- Managers only\n"
                "- High-risk roles (sales, procurement, finance, etc.)\n"
                "- Third parties (agents, distributors, vendors)"
            ),
            type="string",
            default_next="abms.customization_level_6",
        ),

        "abms.customization_level_6": QuestionStep(
            id="abms.customization_level_6",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Investigation Parameter",
            order=6,
            field_name="abms_customization_level",
            text="Are you looking for a standard ABMS / anti-bribery course, or do you need customization to reflect your own policies, code of conduct, or procedures?",
            type="string",
            default_next="abms.languages_7",
        ),

        "abms.languages_7": QuestionStep(
            id="abms.languages_7",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Investigation Parameter",
            order=7,
            field_name="abms_languages",
            text="In which languages do you need e-learning to be available?",
            type="string",
            default_next="abms.sector_examples_8",
        ),

        "abms.sector_examples_8": QuestionStep(
            id="abms.sector_examples_8",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Investigation Parameter",
            order=8,
            field_name="abms_sector_examples",
            text="Do you need any sector-specific examples (e.g. healthcare, oil & gas, public sector, financial services), or are generic examples sufficient?",
            type="string",
            default_next="abms.delivery_mode_9",
        ),

        "abms.delivery_mode_9": QuestionStep(
            id="abms.delivery_mode_9",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Timeline & Priorities",
            order=9,
            field_name="abms_delivery_mode",
            text=(
                "How would you like the training to be delivered:\n"
                "- Through our platform/LMS,\n"
                "- Through your own LMS (SCORM/xAPI package),\n"
                "- Or a combination?"
            ),
            type="string",
            default_next="abms.quiz_and_certificate_10",
        ),

        "abms.quiz_and_certificate_10": QuestionStep(
            id="abms.quiz_and_certificate_10",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Timeline & Priorities",
            order=10,
            field_name="abms_quiz_and_certificate",
            text="Do you require a final test / quiz and certificate of completion for participants?",
            type="string",
            default_next="abms.launch_timeline_11",
        ),

        "abms.launch_timeline_11": QuestionStep(
            id="abms.launch_timeline_11",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Timeline & Priorities",
            order=11,
            field_name="abms_launch_timeline",
            text="When would you ideally like to launch the e-learning, and is there any deadline (e.g. audit, certification, internal campaign)?",
            type="string",
            default_next="abms.tracking_and_reporting_12",
        ),

        "abms.tracking_and_reporting_12": QuestionStep(
            id="abms.tracking_and_reporting_12",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Budget & next steps",
            order=12,
            field_name="abms_tracking_and_reporting",
            text="Do you need tracking & reporting (completion status, scores, certificates) for audits or ISO 37001 / compliance purposes?",
            type="string",
            default_next="abms.rollout_frequency_13",
        ),

        "abms.rollout_frequency_13": QuestionStep(
            id="abms.rollout_frequency_13",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Budget & next steps",
            order=13,
            field_name="abms_rollout_frequency",
            text="Do you expect this to be a one-off rollout or ongoing (e.g. yearly refreshers, onboarding of new employees)?",
            type="string",
            default_next="abms.client_company_profile_14",
        ),

        "abms.client_company_profile_14": QuestionStep(
            id="abms.client_company_profile_14",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Organization & role",
            order=14,
            field_name="abms_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based?",
            type="string",
            default_next="abms.user_role_15",
        ),

        "abms.user_role_15": QuestionStep(
            id="abms.user_role_15",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Organization & role",
            order=15,
            field_name="abms_user_role",
            text="What is your role in this project? (HR, L&D, compliance, legal, internal audit, management, other)",
            type="string",
            # default_next="abms.budget_range_16",
            default_next="abms.other_training_alignment_17",
        ),

        # "abms.budget_range_16": QuestionStep(
        #     id="abms.budget_range_16",
        #     service_code="ABMS",
        #     service_label="ABMS E-Learning",
        #     section="Budget & next steps",
        #     order=16,
        #     field_name="abms_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on number of users, languages and level of customization?",
        #     type="string",
        #     default_next="abms.other_training_alignment_17",
        # ),

        "abms.other_training_alignment_17": QuestionStep(
            id="abms.other_training_alignment_17",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Next Steps & Contact",
            order=17,
            field_name="abms_other_training_alignment",
            text="Are you currently using any other compliance training (e.g. code of conduct, AML, data protection) that this ABMS training needs to align with?",
            type="string",
            default_next="abms.proposal_request_18",
        ),

        "abms.proposal_request_18": QuestionStep(
            id="abms.proposal_request_18",
            service_code="ABMS",
            service_label="ABMS E-Learning",
            section="Next Steps & Contact",
            order=18,
            field_name="abms_proposal_request",
            text="Would you like us to prepare a tailored proposal summarizing audience, languages, delivery mode, and customization level?",
            type="string",
            # default_next="abms.contact_details_19",
            default_next=None,  # selesai → completed
        ),

        # "abms.contact_details_19": QuestionStep(
        #     id="abms.contact_details_19",
        #     service_code="ABMS",
        #     service_label="ABMS E-Learning",
        #     section="Next Steps & Contact",
        #     order=19,
        #     field_name="abms_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and, if needed, schedule a short call?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }

def build_kyc_flow() -> dict[str, QuestionStep]:
    return {
        "kyc.customer_entity_countries_1": QuestionStep(
            id="kyc.customer_entity_countries_1",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Scope Specification",
            order=1,
            field_name="kyc_customer_entity_countries",
            text="In which country or countries are the customers / entities you need to screen mainly based?",
            type="string",
            default_next="kyc.main_objective_3",
        ),

        # "kyc.context_confirmation_2": QuestionStep(
        #     id="kyc.context_confirmation_2",
        #     service_code="KYC",
        #     service_label="Know Your Customer",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="kyc_context_confirmation",
        #     text=(
        #         "Are you looking for Know Your Customer (KYC) screening services to verify customer identities "
        #         "and assess risk profiles for compliance purposes?"
        #     ),
        #     type="string",
        #     default_next="kyc.main_objective_3",
        # ),

        "kyc.main_objective_3": QuestionStep(
            id="kyc.main_objective_3",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Context Confirmation",
            order=3,
            field_name="kyc_main_objective",
            text=(
                "What is the main objective of your KYC needs? For example:\n"
                "- Regulatory compliance (AML, CTF, anti-bribery, sanctions)\n"
                "- Customer onboarding (banks, fintech, insurance, marketplaces)\n"
                "- Periodic re-screening of existing customers\n"
                "- Enhanced due diligence on high-risk profiles\n"
                "- Audit / regulatory reporting requirement\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="kyc.client_company_profile_4",
        ),

        "kyc.client_company_profile_4": QuestionStep(
            id="kyc.client_company_profile_4",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Organization & role",
            order=4,
            field_name="kyc_client_company_profile",
            text=(
                "Can you briefly describe your company and industry, and where you are based? "
                "(e.g. banking, fintech, insurance, investment management, legal/accounting firm, marketplace, regulated enterprise)"
            ),
            type="string",
            default_next="kyc.user_role_5",
        ),

        "kyc.user_role_5": QuestionStep(
            id="kyc.user_role_5",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Organization & role",
            order=5,
            field_name="kyc_user_role",
            text="What is your role in the organization? (compliance, legal, risk, AML/KYC officer, operations, IT/integration, etc.)",
            type="string",
            default_next="kyc.screening_target_6",
        ),

        "kyc.screening_target_6": QuestionStep(
            id="kyc.screening_target_6",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Scope Specification",
            order=6,
            field_name="kyc_screening_target",
            text=(
                "Who do you need to screen:\n"
                "- Individuals (customers, beneficial owners, directors),\n"
                "- Entities (corporate customers, vendors, partners), or\n"
                "- Both?"
            ),
            type="string",
            default_next="kyc.screening_volume_7",
        ),

        "kyc.screening_volume_7": QuestionStep(
            id="kyc.screening_volume_7",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Scope Specification",
            order=7,
            field_name="kyc_screening_volume",
            text="Roughly how many screenings do you expect to perform per month or per year?",
            type="string",
            default_next="kyc.required_checks_8",
        ),

        "kyc.required_checks_8": QuestionStep(
            id="kyc.required_checks_8",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Investigation Parameter",
            order=8,
            field_name="kyc_required_checks",
            text=(
                "Which checks do you require:\n"
                "- Politically Exposed Person (PEP) screening,\n"
                "- Global sanctions screening,\n"
                "- Adverse media screening,\n"
                "- Or a combination of the above?"
            ),
            type="string",
            default_next="kyc.monitoring_cadence_9",
        ),

        "kyc.monitoring_cadence_9": QuestionStep(
            id="kyc.monitoring_cadence_9",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Investigation Parameter",
            order=9,
            field_name="kyc_monitoring_cadence",
            text="Do you need one-time screening per customer, or continuous monitoring with periodic alerts when a customer's risk status changes?",
            type="string",
            default_next="kyc.delivery_mode_10",
        ),

        "kyc.delivery_mode_10": QuestionStep(
            id="kyc.delivery_mode_10",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Investigation Parameter",
            order=10,
            field_name="kyc_delivery_mode",
            text=(
                "How would you prefer to perform screenings:\n"
                "- Single-name online lookup,\n"
                "- Bulk / batch upload of files,\n"
                "- API integration into your existing onboarding/CRM system,\n"
                "- Or a combination?"
            ),
            type="string",
            default_next="kyc.turnaround_expectation_11",
        ),

        "kyc.turnaround_expectation_11": QuestionStep(
            id="kyc.turnaround_expectation_11",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Timeline & Priorities",
            order=11,
            field_name="kyc_turnaround_expectation",
            text="What is your expected turnaround time per screening or per batch? (e.g. instant for online single screenings, 3 - 5 minutes for batch screenings)",
            type="string",
            default_next="kyc.compliance_requirements_12",
        ),

        "kyc.compliance_requirements_12": QuestionStep(
            id="kyc.compliance_requirements_12",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Timeline & Priorities",
            order=12,
            field_name="kyc_compliance_requirements",
            text="Are there any compliance or data protection requirements we should align with? (e.g. PDPL, GDPR, OJK / regulator guidance, internal group policies)",
            type="string",
            default_next="kyc.go_live_timeline_13",
        ),

        "kyc.go_live_timeline_13": QuestionStep(
            id="kyc.go_live_timeline_13",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Timeline & Priorities",
            order=13,
            field_name="kyc_go_live_timeline",
            text="When would you ideally like the KYC service to be operational? (approximate go-live date or critical milestone)",
            type="string",
            default_next="kyc.deliverable_format_14",
        ),

        "kyc.deliverable_format_14": QuestionStep(
            id="kyc.deliverable_format_14",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Budget & next steps",
            order=14,
            field_name="kyc_deliverable_format",
            text=(
                "What deliverable format do you prefer:\n"
                "- Individual screening reports per customer (PDF / exportable),\n"
                "- Dashboard-style monitoring with alerts,\n"
                "- Both?"
            ),
            type="string",
            # default_next="kyc.budget_range_15",
            default_next="kyc.rollout_type_16",
        ),

        # "kyc.budget_range_15": QuestionStep(
        #     id="kyc.budget_range_15",
        #     service_code="KYC",
        #     service_label="Know Your Customer",
        #     section="Budget & next steps",
        #     order=15,
        #     field_name="kyc_budget_range",
        #     text="Do you already have a budget range in mind, or would you like us to propose options based on volume, check types and integration mode?",
        #     type="string",
        #     default_next="kyc.rollout_type_16",
        # ),

        "kyc.rollout_type_16": QuestionStep(
            id="kyc.rollout_type_16",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Next Steps & Contact",
            order=16,
            field_name="kyc_rollout_type",
            text="Is this a one-off rollout, or do you expect this to be an ongoing service (e.g. continuous monitoring, recurring batches, expanding customer base)?",
            type="string",
            default_next="kyc.proposal_request_17",
        ),

        "kyc.proposal_request_17": QuestionStep(
            id="kyc.proposal_request_17",
            service_code="KYC",
            service_label="Know Your Customer",
            section="Next Steps & Contact",
            order=17,
            field_name="kyc_proposal_request",
            text="Would you like us to prepare a tailored proposal summarizing scope (check types, volumes, integration mode and monitoring approach)?",
            type="string",
            # default_next="kyc.contact_details_18",
            default_next=None,  # selesai → completed
        ),

        # "kyc.contact_details_18": QuestionStep(
        #     id="kyc.contact_details_18",
        #     service_code="KYC",
        #     service_label="Know Your Customer",
        #     section="Next Steps & Contact",
        #     order=18,
        #     field_name="kyc_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and follow up with you?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }


def build_cli_flow() -> dict[str, QuestionStep]:
    return {
        "cli.claim_locations_1": QuestionStep(
            id="cli.claim_locations_1",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Scope Specification",
            order=1,
            field_name="cli_claim_locations",
            text="In which region or province(s) of Indonesia (or other Southeast Asian countries) are the claims mainly located? Do any cases involve remote areas (e.g. Kalimantan, Sulawesi, Papua, NTT, Sumatera)?",
            type="string",
            default_next="cli.claim_types_3",
        ),

        # "cli.context_confirmation_2": QuestionStep(
        #     id="cli.context_confirmation_2",
        #     service_code="CLI",
        #     service_label="Claim Investigation",
        #     section="Context Confirmation",
        #     order=2,
        #     field_name="cli_context_confirmation",
        #     text=(
        #         "Are you looking for claim investigation services to verify the validity of insurance claims "
        #         "submitted to your company?"
        #     ),
        #     type="string",
        #     default_next="cli.claim_types_3",
        # ),

        "cli.claim_types_3": QuestionStep(
            id="cli.claim_types_3",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Context Confirmation",
            order=3,
            field_name="cli_claim_types",
            text=(
                "What types of claims do you need investigated? For example:\n"
                "- Inpatient / health claims\n"
                "- Death claims\n"
                "- Accident / PADD (Personal Accident, Death & Disability) claims\n"
                "- Property or vehicle claims\n"
                "- Suspicious or high-value claims\n"
                "- Other (please specify)"
            ),
            type="string",
            default_next="cli.client_company_profile_4",
        ),

        "cli.client_company_profile_4": QuestionStep(
            id="cli.client_company_profile_4",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Organization & role",
            order=4,
            field_name="cli_client_company_profile",
            text="Can you briefly describe your company and industry, and where you are based? (e.g. life insurance, general insurance, health insurance, reinsurance, broker)",
            type="string",
            default_next="cli.user_role_5",
        ),

        "cli.user_role_5": QuestionStep(
            id="cli.user_role_5",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Organization & role",
            order=5,
            field_name="cli_user_role",
            text="What is your role in the company? (claims, anti-fraud / SIU, underwriting, compliance, legal, operations, etc.)",
            type="string",
            default_next="cli.case_summary_6",
        ),

        "cli.case_summary_6": QuestionStep(
            id="cli.case_summary_6",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Scope Specification",
            order=6,
            field_name="cli_case_summary",
            text="Can you briefly describe the case or claim circumstances we would be investigating? (a few sentences are enough)",
            type="string",
            default_next="cli.case_volume_7",
        ),

        "cli.case_volume_7": QuestionStep(
            id="cli.case_volume_7",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Scope Specification",
            order=7,
            field_name="cli_case_volume",
            text="Roughly how many claim cases do you expect to send for investigation per month or per year?",
            type="string",
            default_next="cli.claim_value_range_8",
        ),

        "cli.claim_value_range_8": QuestionStep(
            id="cli.claim_value_range_8",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Investigation Parameter",
            order=8,
            field_name="cli_claim_value_range",
            text="What is the approximate value range of the claims to be investigated (per case or across the portfolio)?",
            type="string",
            default_next="cli.available_documents_9",
        ),

        "cli.available_documents_9": QuestionStep(
            id="cli.available_documents_9",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Investigation Parameter",
            order=9,
            field_name="cli_available_documents",
            text=(
                "What documents and information can you provide for each case? For example:\n"
                "- Claim documents and policy details\n"
                "- A detailed account of the incident\n"
                "- Contact information for claimants, beneficiaries and witnesses\n"
                "- Supporting evidence (medical records, police reports, photos, etc.)"
            ),
            type="string",
            default_next="cli.investigation_activities_10",
        ),

        "cli.investigation_activities_10": QuestionStep(
            id="cli.investigation_activities_10",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Investigation Parameter",
            order=10,
            field_name="cli_investigation_activities",
            text=(
                "What investigation activities should we focus on:\n"
                "- Document and medical record verification,\n"
                "- Interviews with claimants, witnesses and providers,\n"
                "- Site visits and field investigation,\n"
                "- Or a combination of the above?"
            ),
            type="string",
            default_next="cli.discretion_preference_11",
        ),

        "cli.discretion_preference_11": QuestionStep(
            id="cli.discretion_preference_11",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Timeline & Priorities",
            order=11,
            field_name="cli_discretion_preference",
            text="Should the investigation be conducted as discreetly as possible, or is direct notification of the claimant / beneficiary (e.g. announced interviews and document requests) acceptable?",
            type="string",
            default_next="cli.constraints_12",
        ),

        "cli.constraints_12": QuestionStep(
            id="cli.constraints_12",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Timeline & Priorities",
            order=12,
            field_name="cli_constraints",
            text=(
                "Are there any constraints we must respect? For example:\n"
                "- Strict confidentiality requirements,\n"
                "- Restrictions on contacting certain parties,\n"
                "- Regulatory or insurance association guidelines (e.g. OJK, AAJI, AAUI),\n"
                "- Sensitivity around bereaved families (for death claims)"
            ),
            type="string",
            default_next="cli.turnaround_expectation_13",
        ),

        "cli.turnaround_expectation_13": QuestionStep(
            id="cli.turnaround_expectation_13",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Timeline & Priorities",
            order=13,
            field_name="cli_turnaround_expectation",
            text="What is your expected turnaround time per case? (general benchmark is 14 - 15 working days; faster turnaround may be possible for urgent cases)",
            type="string",
            default_next="cli.deliverable_preference_14",
        ),

        "cli.deliverable_preference_14": QuestionStep(
            id="cli.deliverable_preference_14",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Budget & next steps",
            order=14,
            field_name="cli_deliverable_preference",
            text=(
                "What type of deliverable do you prefer:\n"
                "- A concise findings summary with a clear conclusion (valid / suspicious / fraudulent),\n"
                "- A detailed report covering evidence, interviews and site visit documentation,\n"
                "- Both?"
            ),
            type="string",
            # default_next="cli.budget_range_15",
            default_next="cli.case_frequency_16",
        ),

        # "cli.budget_range_15": QuestionStep(
        #     id="cli.budget_range_15",
        #     service_code="CLI",
        #     service_label="Claim Investigation",
        #     section="Budget & next steps",
        #     order=15,
        #     field_name="cli_budget_range",
        #     text="Do you already have a budget range in mind (per case or for a bulk volume), or would you like us to propose options based on case volume, complexity and geography?",
        #     type="string",
        #     default_next="cli.case_frequency_16",
        # ),

        "cli.case_frequency_16": QuestionStep(
            id="cli.case_frequency_16",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Next Steps & Contact",
            order=16,
            field_name="cli_case_frequency",
            text="Is this a one-off case, or do you expect ongoing claim investigation needs (e.g. monthly volume, dedicated SIU / anti-fraud support)?",
            type="string",
            default_next="cli.proposal_request_17",
        ),

        "cli.proposal_request_17": QuestionStep(
            id="cli.proposal_request_17",
            service_code="CLI",
            service_label="Claim Investigation",
            section="Next Steps & Contact",
            order=17,
            field_name="cli_proposal_request",
            text="Would you like us to prepare a tailored proposal summarizing scope (claim types, volume, geography, deliverable format and turnaround)?",
            type="string",
            # default_next="cli.contact_details_18",
            default_next=None,  # selesai → completed
        ),

        # "cli.contact_details_18": QuestionStep(
        #     id="cli.contact_details_18",
        #     service_code="CLI",
        #     service_label="Claim Investigation",
        #     section="Next Steps & Contact",
        #     order=18,
        #     field_name="cli_contact_details",
        #     text="What is the best email address and phone/WhatsApp number for us to send the proposal and follow up with you?",
        #     type="string",
        #     default_next=None,  # selesai → completed
        # ),
    }


FLOW_REGISTRY: dict[str, dict[str, QuestionStep]] = {
    "EBS": build_ebs_flow(),
    "DDC": build_ddc_flow(),
    "MSG": build_msg_flow(),
    "AST": build_ast_flow(),
    "WBS": build_wbs_flow(),
    "FRI": build_fri_flow(),
    "MSY": build_msy_flow(),
    "SKT": build_skt_flow(),
    "CMI": build_cmi_flow(),
    "NUI": build_nui_flow(),
    "ACI": build_aci_flow(),
    "PTI": build_pti_flow(),
    "ABMS": build_abms_flow(),
    "KYC": build_kyc_flow(),
    "CLI": build_cli_flow(),
}