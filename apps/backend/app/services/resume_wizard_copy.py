"""Deterministic resume-wizard copy in each supported content language.

Sections are pure data, so there is no per-section copy: a question about a
section falls back to ``section_generic``, a localized template parameterised by
the section's own heading. Only the fixed wizard steps (intro, contact, review)
have bespoke copy.
"""

_COPY: dict[str, dict[str, str]] = {
    "en": {
        "intro": "Hi — I'll help you build your master resume. What's your name, and what kind of role are you going for?",
        "contact": "What's the best email, phone, or links (LinkedIn / GitHub / site) to include?",
        "review": "Let's review what's here before we create your master resume.",
        "next": "What would you like to add next?",
        "section_generic": "Tell me about {heading}: what should this section include?",
        "warning_name": "Add your name — it's required to create your resume.",
        "warning_contact": "Add at least one contact method (email, phone, or a link).",
        "warning_section_empty": "{heading} is empty — skip only if that's intentional.",
    },
    "es": {
        "intro": "Hola, te ayudaré a crear tu currículum maestro. ¿Cómo te llamas y qué tipo de puesto buscas?",
        "contact": "¿Qué correo, teléfono o enlaces (LinkedIn, GitHub o sitio web) quieres incluir?",
        "review": "Revisemos el contenido antes de crear tu currículum maestro.",
        "next": "¿Qué te gustaría añadir a continuación?",
        "section_generic": "Cuéntame sobre {heading}: ¿qué debería incluir esta sección?",
        "warning_name": "Añade tu nombre; es necesario para crear el currículum.",
        "warning_contact": "Añade al menos un medio de contacto (correo, teléfono o enlace).",
        "warning_section_empty": "{heading} está vacío; omítelo solo si es intencional.",
    },
    "zh": {
        "intro": "你好，我会帮你创建主简历。你叫什么名字，想应聘哪类职位？",
        "contact": "你想添加哪个电子邮箱、电话号码或链接（LinkedIn、GitHub 或个人网站）？",
        "review": "创建主简历前，让我们先检查现有内容。",
        "next": "接下来你想添加什么？",
        "section_generic": "请介绍「{heading}」：这一部分应该包含哪些内容？",
        "warning_name": "请添加姓名；创建简历时必须提供姓名。",
        "warning_contact": "请至少添加一种联系方式（电子邮箱、电话或链接）。",
        "warning_section_empty": "「{heading}」为空；仅在这是有意为之时跳过。",
    },
    "ja": {
        "intro": "こんにちは。マスター履歴書の作成をお手伝いします。お名前と希望する職種を教えてください。",
        "contact": "掲載するメールアドレス、電話番号、リンク（LinkedIn、GitHub、サイト）を教えてください。",
        "review": "マスター履歴書を作成する前に、内容を確認しましょう。",
        "next": "次に何を追加しますか？",
        "section_generic": "「{heading}」について教えてください。このセクションには何を含めますか？",
        "warning_name": "氏名を追加してください。履歴書の作成に必要です。",
        "warning_contact": "連絡先（メール、電話、リンク）を少なくとも1つ追加してください。",
        "warning_section_empty": "「{heading}」が空です。意図的な場合のみスキップしてください。",
    },
    "pt": {
        "intro": "Olá, vou ajudar você a criar seu currículo mestre. Qual é o seu nome e que tipo de cargo você procura?",
        "contact": "Qual e-mail, telefone ou links (LinkedIn, GitHub ou site) você quer incluir?",
        "review": "Vamos revisar o conteúdo antes de criar seu currículo mestre.",
        "next": "O que você gostaria de adicionar agora?",
        "section_generic": "Conte sobre {heading}: o que esta seção deve incluir?",
        "warning_name": "Adicione seu nome; ele é obrigatório para criar o currículo.",
        "warning_contact": "Adicione pelo menos um contato (e-mail, telefone ou link).",
        "warning_section_empty": "{heading} está vazio; pule apenas se isso for intencional.",
    },
    "fr": {
        "intro": "Bonjour, je vais vous aider à créer votre CV principal. Quel est votre nom et quel type de poste recherchez-vous ?",
        "contact": "Quelle adresse e-mail, quel téléphone ou quels liens (LinkedIn, GitHub ou site) souhaitez-vous inclure ?",
        "review": "Vérifions le contenu avant de créer votre CV principal.",
        "next": "Que souhaitez-vous ajouter ensuite ?",
        "section_generic": "Parlez-moi de {heading} : que doit contenir cette section ?",
        "warning_name": "Ajoutez votre nom ; il est nécessaire pour créer le CV.",
        "warning_contact": "Ajoutez au moins un moyen de contact (e-mail, téléphone ou lien).",
        "warning_section_empty": "{heading} est vide ; ne la passez que si c’est intentionnel.",
    },
    "ko": {
        "intro": "안녕하세요. 마스터 이력서 작성을 도와드리겠습니다. 이름과 희망하는 직무를 알려 주세요.",
        "contact": "기재할 이메일, 전화번호 또는 링크(LinkedIn, GitHub, 웹사이트)를 알려 주세요.",
        "review": "마스터 이력서를 만들기 전에 내용을 검토해 보겠습니다.",
        "next": "다음으로 무엇을 추가하시겠습니까?",
        "section_generic": "「{heading}」에 대해 알려 주세요. 이 항목에는 무엇을 포함할까요?",
        "warning_name": "이름을 추가해 주세요. 이력서 생성에 필요합니다.",
        "warning_contact": "연락처(이메일, 전화 또는 링크)를 하나 이상 추가해 주세요.",
        "warning_section_empty": "「{heading}」이(가) 비어 있습니다. 의도한 경우에만 건너뛰세요.",
    },
}

WIZARD_COPY_KEYS: tuple[str, ...] = tuple(_COPY["en"])


def wizard_copy(language: str, key: str) -> str:
    """Return deterministic wizard copy, falling back to English."""
    localized = _COPY.get(language, _COPY["en"])
    return localized.get(key, _COPY["en"][key])


def section_question(language: str, heading: str) -> str:
    """Localized fallback question for any section, named by its heading."""
    return wizard_copy(language, "section_generic").format(heading=heading)


def section_empty_warning(language: str, heading: str) -> str:
    """Localized review note that a section has no content yet."""
    return wizard_copy(language, "warning_section_empty").format(heading=heading)
