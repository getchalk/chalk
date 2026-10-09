"""
src/ui/i18n.py - Unified Desktop Internationalization (i18n) Engine for Chalk.
Full language parity across English (en), German (de), French (fr), Spanish (es), and Chinese (zh).
Pure Python lightweight architecture with zero external pip dependencies and 0 emojis.
"""

import os
import logging
from typing import Dict, Any, Optional

from src.engine.config import (
    get_ui_language as config_get_ui_language,
    set_ui_language as config_set_ui_language,
)

logger = logging.getLogger("chalk.ui.i18n")

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "zh": "中文",
}

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # ----------------------------------------------------
    # HUD Header & Status
    # ----------------------------------------------------
    "status_recording": {
        "en": "RECORDING ACTIVE ({time})",
        "de": "AUFNAHME AKTIV ({time})",
        "fr": "ENREGISTREMENT ACTIF ({time})",
        "es": "GRABACIÓN ACTIVA ({time})",
        "zh": "录音活跃 ({time})",
    },
    "status_paused": {
        "en": "PAUSED ({time})",
        "de": "PAUSIERT ({time})",
        "fr": "EN PAUSE ({time})",
        "es": "PAUSADO ({time})",
        "zh": "已暂停 ({time})",
    },
    "status_processing": {
        "en": "PROCESSING...",
        "de": "VERARBEITUNG...",
        "fr": "TRAITEMENT...",
        "es": "PROCESANDO...",
        "zh": "处理中...",
    },
    "status_standby": {
        "en": "STANDBY",
        "de": "BEREIT",
        "fr": "EN VEILLE",
        "es": "EN ESPERA",
        "zh": "待机",
    },
    "status_byok_connected": {
        "en": "Direct BYOK Connected",
        "de": "Direkt-BYOK verbunden",
        "fr": "BYOK direct connecté",
        "es": "BYOK directo conectado",
        "zh": "直接 BYOK 已连接",
    },
    "status_session_context": {
        "en": "Session Context",
        "de": "Sitzungskontext",
        "fr": "Contexte de session",
        "es": "Contexto de sesión",
        "zh": "会话上下文",
    },
    "status_break_detected": {
        "en": "Break detected (silence)",
        "de": "Pause erkannt (Stille)",
        "fr": "Pause détectée (silence)",
        "es": "Pausa detectada (silencio)",
        "zh": "检测到休会（静音）",
    },
    "status_slides_ready": {
        "en": "Slides attached: {count} pages",
        "de": "Folien angehängt: {count} Seiten",
        "fr": "Diapositives attachées : {count} pages",
        "es": "Diapositivas adjuntas: {count} páginas",
        "zh": "已附加幻灯片：{count} 页",
    },
    "status_photo_ready": {
        "en": "Whiteboard photos: {count} attached",
        "de": "Tafelfotos: {count} angehängt",
        "fr": "Photos de tableau : {count} attachées",
        "es": "Fotos de pizarra: {count} adjuntas",
        "zh": "白板照片：已附加 {count} 张",
    },
    "hud_screen_mirror": {
        "en": "SCREEN CAPTURE",
        "de": "BILDSCHIRMAUFNAHME",
        "fr": "CAPTURE D'ECRAN",
        "es": "CAPTURA DE PANTALLA",
        "zh": "屏幕捕获",
    },
    "hud_display_status": {
        "en": "PRIMARY DISPLAY",
        "de": "HAUPTBILDSCHIRM",
        "fr": "ECRAN PRINCIPAL",
        "es": "PANTALLA PRINCIPAL",
        "zh": "主显示屏",
    },
    "hud_listening_speech": {
        "en": "Listening to microphone feed... Live spoken audio will appear here.",
        "de": "Mikrofon aktiv... Gesprochenes Audio erscheint hier.",
        "fr": "Microphone actif... Les paroles apparaitront ici.",
        "es": "Microfono activo... El audio hablado aparecera aqui.",
        "zh": "麦克风监听中... 现场语音将在此实时呈现。",
    },

    # ----------------------------------------------------
    # Action Buttons & Tooltips
    # ----------------------------------------------------
    "btn_attach_slides": {
        "en": "Attach Slides",
        "de": "Folien anhängen",
        "fr": "Joindre diapositives",
        "es": "Adjuntar diapositivas",
        "zh": "附加幻灯片",
    },
    "btn_snip_screen": {
        "en": "Snip Screen [Alt+S]",
        "de": "Bildschirmfoto [Alt+S]",
        "fr": "Capture d'écran [Alt+S]",
        "es": "Capturar pantalla [Alt+S]",
        "zh": "截取屏幕 [Alt+S]",
    },
    "btn_cam": {
        "en": "Whiteboard Camera [QR]",
        "de": "Tafel-Kamera [QR]",
        "fr": "Caméra tableau [QR]",
        "es": "Cámara de pizarra [QR]",
        "zh": "白板相机 [QR]",
    },
    "btn_rewind_90s": {
        "en": "Rewind 90s",
        "de": "Rücklauf 90s",
        "fr": "Rembobiner 90s",
        "es": "Rebobinar 90s",
        "zh": "快退 90秒",
    },
    "btn_search_archive": {
        "en": "Search Archive [Alt+F]",
        "de": "Archiv durchsuchen [Alt+F]",
        "fr": "Rechercher archives [Alt+F]",
        "es": "Buscar archivo [Alt+F]",
        "zh": "搜索归档 [Alt+F]",
    },
    "btn_anki_export": {
        "en": "Export Anki [TSV]",
        "de": "Anki exportieren [TSV]",
        "fr": "Exporter Anki [TSV]",
        "es": "Exportar Anki [TSV]",
        "zh": "导出 Anki [TSV]",
    },
    "btn_pdf_export": {
        "en": "Export PDF",
        "de": "Export PDF",
        "fr": "Exporter PDF",
        "es": "Exportar PDF",
        "zh": "导出 PDF",
    },
    "btn_copy_notes": {
        "en": "Copy Notes",
        "de": "Notizen kopieren",
        "fr": "Copier notes",
        "es": "Copiar notas",
        "zh": "复制笔记",
    },
    "btn_obsidian": {
        "en": "Obsidian",
        "de": "Obsidian",
        "fr": "Obsidian",
        "es": "Obsidian",
        "zh": "Obsidian",
    },
    "btn_system_editor": {
        "en": "System Editor",
        "de": "System-Editor",
        "fr": "Éditeur système",
        "es": "Editor del sistema",
        "zh": "系统编辑器",
    },
    "btn_settings": {
        "en": "Settings",
        "de": "Einstellungen",
        "fr": "Paramètres",
        "es": "Ajustes",
        "zh": "设置",
    },
    "btn_finish": {
        "en": "Finish [F9]",
        "de": "Beenden [F9]",
        "fr": "Terminer [F9]",
        "es": "Finalizar [F9]",
        "zh": "完成 [F9]",
    },
    "btn_socratic_debrief": {
        "en": "Recall [F9]",
        "de": "Recall [F9]",
        "fr": "Rappel [F9]",
        "es": "Recuerdo [F9]",
        "zh": "回顾 [F9]",
    },
    "btn_send": {
        "en": "Send",
        "de": "Senden",
        "fr": "Envoyer",
        "es": "Enviar",
        "zh": "发送",
    },
    "btn_close": {
        "en": "Close",
        "de": "Schließen",
        "fr": "Fermer",
        "es": "Cerrar",
        "zh": "关闭",
    },
    "btn_copy_link": {
        "en": "Copy Link",
        "de": "Link kopieren",
        "fr": "Copier le lien",
        "es": "Copiar enlace",
        "zh": "复制链接",
    },
    "btn_save": {
        "en": "Save & Validate",
        "de": "Speichern & Prüfen",
        "fr": "Enregistrer & Valider",
        "es": "Guardar y Validar",
        "zh": "保存并验证",
    },
    "btn_cancel": {
        "en": "Cancel",
        "de": "Abbrechen",
        "fr": "Annuler",
        "es": "Cancelar",
        "zh": "取消",
    },
    "btn_test_key": {
        "en": "Test Key",
        "de": "Schlüssel testen",
        "fr": "Tester la clé",
        "es": "Probar clave",
        "zh": "测试密钥",
    },
    "btn_browse": {
        "en": "Browse...",
        "de": "Durchsuchen...",
        "fr": "Parcourir...",
        "es": "Examinar...",
        "zh": "浏览...",
    },
    "btn_open_editor": {
        "en": "Open in Editor",
        "de": "Im Editor öffnen",
        "fr": "Ouvrir dans l'éditeur",
        "es": "Abrir en editor",
        "zh": "在编辑器中打开",
    },
    "btn_load_notes": {
        "en": "Load into Notes",
        "de": "In Notizen laden",
        "fr": "Charger dans les notes",
        "es": "Cargar en notas",
        "zh": "载入笔记",
    },

    # ----------------------------------------------------
    # Scratchpad & Tabs
    # ----------------------------------------------------
    "scratchpad_label": {
        "en": "User Scratchpad (Shorthand & Outline Anchor):",
        "de": "User Scratchpad (Gliederung & Notizen-Anker):",
        "fr": "Bloc-notes utilisateur (Plan & Ancrage) :",
        "es": "Bloc de notas de usuario (Esquema y Anclaje):",
        "zh": "用户暂存板（速记与大纲锚点）：",
    },
    "scratchpad_placeholder": {
        "en": "Type your live outline notes here... Chalk anchors derivations to your thoughts.",
        "de": "Geben Sie hier Ihre Live-Gliederungsnotizen ein... Chalk verknüpft Herleitungen mit Ihren Gedanken.",
        "fr": "Tapez vos notes de plan en direct ici... Chalk ancre les dérivations à vos pensées.",
        "es": "Escriba aquí sus notas de esquema en vivo... Chalk ancla las deducciones a sus pensamientos.",
        "zh": "在此输入您的实时大纲笔记... Chalk 会将推导与您的思路锚定。",
    },
    "tab_copilot": {
        "en": "Copilot & History",
        "de": "Copilot & Verlauf",
        "fr": "Copilote et historique",
        "es": "Copiloto e historial",
        "zh": "副驾驶与历史",
    },
    "tab_notes": {
        "en": "Live KaTeX Notes",
        "de": "Live KaTeX Notizen",
        "fr": "Notes KaTeX en direct",
        "es": "Notas KaTeX en vivo",
        "zh": "实时 KaTeX 笔记",
    },
    "chat_history_placeholder": {
        "en": "Responses, rewind transcripts, and clickable timestamps [HH:MM:SS] appear here...",
        "de": "Antworten, Rewind-Transkripte und klickbare Zeitstempel [HH:MM:SS] erscheinen hier...",
        "fr": "Les réponses, transcriptions et horodatages cliquables [HH:MM:SS] s'affichent ici...",
        "es": "Las respuestas, transcripciones y marcas de tiempo cliqueables [HH:MM:SS] aparecen aquí...",
        "zh": "回复、快退转录和可点击的时间戳 [HH:MM:SS] 将显示在此处...",
    },
    "notes_browser_placeholder": {
        "en": "Live KaTeX rendered notes with verified mathematical formulas appear here...",
        "de": "Live KaTeX gerenderte Notizen mit verifizierten mathematischen Formeln erscheinen hier...",
        "fr": "Les notes rendues en KaTeX avec formules mathématiques vérifiées s'affichent ici...",
        "es": "Las notas renderizadas en KaTeX con fórmulas matemáticas verificadas aparecen aquí...",
        "zh": "实时 KaTeX 渲染的笔记及验证的数学公式将显示在此处...",
    },
    "prompt_input_placeholder": {
        "en": "Ask synthesis copilot (e.g. clarify theorem or re-derive equation)...",
        "de": "Synthese-Copilot fragen (z. B. Satz klären oder Gleichung herleiten)...",
        "fr": "Demander au copilote (ex. clarifier un théorème ou redériver une équation)...",
        "es": "Preguntar al copiloto (ej. aclarar teorema o re-deducir ecuación)...",
        "zh": "向合成副驾驶提问（如：澄清定理或重新推导方程）...",
    },

    # ----------------------------------------------------
    # Whiteboard Camera Dialog
    # ----------------------------------------------------
    "wb_dialog_title": {
        "en": "Whiteboard Camera Pairing [LAN]",
        "de": "Tafel-Kamera Kopplung [LAN]",
        "fr": "Couplage caméra tableau [LAN]",
        "es": "Emparejamiento de cámara de pizarra [LAN]",
        "zh": "白板相机配对 [局域网]",
    },
    "wb_subtitle": {
        "en": "Scan the code with your smartphone. Physical whiteboard photos stream silently into notes.",
        "de": "Scanne den Code mit deinem Smartphone. Fotos der physischen Tafel fließen lautlos in die Notizen ein.",
        "fr": "Scannez le code avec votre smartphone. Les photos de tableau s'intègrent silencieusement aux notes.",
        "es": "Escanee el código con su teléfono. Las fotos de la pizarra se integran silenciosamente a las notas.",
        "zh": "用手机扫描二维码。实体黑板照片将静默融入笔记。",
    },
    "wb_waiting": {
        "en": "Waiting for photos...",
        "de": "Warte auf Fotos...",
        "fr": "En attente de photos...",
        "es": "Esperando fotos...",
        "zh": "等待照片...",
    },
    "wb_connected": {
        "en": "Connected: {count} photos received",
        "de": "Verbunden: {count} Fotos empfangen",
        "fr": "Connecté : {count} photos reçues",
        "es": "Conectado: {count} fotos recibidas",
        "zh": "已连接：已接收 {count} 张照片",
    },
    "wb_server_offline": {
        "en": "Companion server offline",
        "de": "Begleit-Server offline",
        "fr": "Serveur compagnon hors ligne",
        "es": "Servidor complementario sin conexión",
        "zh": "配套服务器离线",
    },
    "wb_info_footer": {
        "en": "100% local network &bull; No app download required &bull; Highest synthesis priority",
        "de": "100% lokales Netzwerk &bull; Kein App-Download erforderlich &bull; Höchste Synthese-Priorität",
        "fr": "Réseau 100% local &bull; Aucun téléchargement requis &bull; Priorité de synthèse maximale",
        "es": "Red 100% local &bull; No requiere descarga de app &bull; Máxima prioridad de síntesis",
        "zh": "100% 本地局域网 &bull; 无需下载应用 &bull; 最高合成优先级",
    },

    # ----------------------------------------------------
    # Mini Audio Player
    # ----------------------------------------------------
    "player_time_label": {
        "en": "{duration}s audio snippet",
        "de": "{duration}s Audio-Ausschnitt",
        "fr": "Extrait audio de {duration}s",
        "es": "Fragmento de audio de {duration}s",
        "zh": "{duration}秒 音频片段",
    },

    # ----------------------------------------------------
    # Settings Dialog
    # ----------------------------------------------------
    "settings_dialog_title": {
        "en": "Chalk — Settings & BYOK Security",
        "de": "Chalk — Einstellungen & BYOK-Sicherheit",
        "fr": "Chalk — Paramètres & Sécurité BYOK",
        "es": "Chalk — Configuración y Seguridad BYOK",
        "zh": "Chalk — 设置与 BYOK 安全",
    },
    "settings_header_title": {
        "en": "Model & BYOK Security",
        "de": "Modell & BYOK-Sicherheit",
        "fr": "Modèle & Sécurité BYOK",
        "es": "Modelo y Seguridad BYOK",
        "zh": "模型与 BYOK 安全",
    },
    "settings_header_subtitle": {
        "en": "Local-First: Credentials live exclusively in your local OS native vault.",
        "de": "Local-First: Zugangsdaten liegen ausschließlich im lokalen Betriebssystem-Schlüsselbund.",
        "fr": "Local-First : Les identifiants résident exclusivement dans le trousseau sécurisé de l'OS.",
        "es": "Local-First: Las credenciales residen exclusivamente en el llavero nativo del SO.",
        "zh": "本地优先：凭据仅保存在本地操作系统原生安全存储中。",
    },
    "settings_model_label": {
        "en": "Active Synthesis Model:",
        "de": "Aktives Synthese-Modell:",
        "fr": "Modèle de synthèse actif :",
        "es": "Modelo de síntesis activo:",
        "zh": "当前合成模型：",
    },
    "settings_model_gemini": {
        "en": "Gemini 2.5 Flash (1M Token Context, Recommended)",
        "de": "Gemini 2.5 Flash (1M Token Kontext, Empfohlen)",
        "fr": "Gemini 2.5 Flash (Contexte 1M jetons, Recommandé)",
        "es": "Gemini 2.5 Flash (Contexto 1M tokens, Recomendado)",
        "zh": "Gemini 2.5 Flash（100万 Token 上下文，推荐）",
    },
    "settings_model_claude": {
        "en": "Claude 3.7 Sonnet (Anthropic BYOK)",
        "de": "Claude 3.7 Sonnet (Anthropic BYOK)",
        "fr": "Claude 3.7 Sonnet (Anthropic BYOK)",
        "es": "Claude 3.7 Sonnet (Anthropic BYOK)",
        "zh": "Claude 3.7 Sonnet（Anthropic BYOK）",
    },
    "settings_model_gpt": {
        "en": "GPT-4o (OpenAI BYOK)",
        "de": "GPT-4o (OpenAI BYOK)",
        "fr": "GPT-4o (OpenAI BYOK)",
        "es": "GPT-4o (OpenAI BYOK)",
        "zh": "GPT-4o（OpenAI BYOK）",
    },
    "model_gemini_25_flash": {
        "en": "Gemini 2.5 Flash (Recommended • Free Tier)",
        "de": "Gemini 2.5 Flash (Empfohlen • Free Tier)",
        "fr": "Gemini 2.5 Flash (Recommandé • Niveau gratuit)",
        "es": "Gemini 2.5 Flash (Recomendado • Nivel gratuito)",
        "zh": "Gemini 2.5 Flash（推荐 • 免费层）",
    },
    "model_gemini_25_pro": {
        "en": "Gemini 2.5 Pro (Deep Math & Reasoning)",
        "de": "Gemini 2.5 Pro (Mathematik & Reasoning)",
        "fr": "Gemini 2.5 Pro (Mathématiques approfondies & Raisonnement)",
        "es": "Gemini 2.5 Pro (Matemáticas profundas y Razonamiento)",
        "zh": "Gemini 2.5 Pro（深度数学与推理）",
    },
    "model_gemini_20_flash": {
        "en": "Gemini 2.0 Flash (Next-Gen Real-Time)",
        "de": "Gemini 2.0 Flash (Next-Gen Echtzeit)",
        "fr": "Gemini 2.0 Flash (Temps réel nouvelle génération)",
        "es": "Gemini 2.0 Flash (Tiempo real de próxima generación)",
        "zh": "Gemini 2.0 Flash（次世代实时响应）",
    },
    "model_gemini_20_flash_lite": {
        "en": "Gemini 2.0 Flash-Lite (High Speed & Low Latency)",
        "de": "Gemini 2.0 Flash-Lite (Hohe Geschwindigkeit & Niedrige Latenz)",
        "fr": "Gemini 2.0 Flash-Lite (Haute vitesse & Faible latence)",
        "es": "Gemini 2.0 Flash-Lite (Alta velocidad y baja latencia)",
        "zh": "Gemini 2.0 Flash-Lite（高速低延迟）",
    },
    "model_gemini_15_pro": {
        "en": "Gemini 1.5 Pro (2M Long Context Archive)",
        "de": "Gemini 1.5 Pro (2M Long Context Archiv)",
        "fr": "Gemini 1.5 Pro (Archive long contexte 2M)",
        "es": "Gemini 1.5 Pro (Archivo de contexto largo de 2M)",
        "zh": "Gemini 1.5 Pro（200万长上下文归档）",
    },
    "model_claude_37_sonnet": {
        "en": "Claude 3.7 Sonnet (Hybrid Reasoning)",
        "de": "Claude 3.7 Sonnet (Hybrides Reasoning)",
        "fr": "Claude 3.7 Sonnet (Raisonnement hybride)",
        "es": "Claude 3.7 Sonnet (Razonamiento híbrido)",
        "zh": "Claude 3.7 Sonnet（混合推理）",
    },
    "model_claude_35_sonnet": {
        "en": "Claude 3.5 Sonnet (Technical Analysis)",
        "de": "Claude 3.5 Sonnet (Technische Analyse)",
        "fr": "Claude 3.5 Sonnet (Analyse technique)",
        "es": "Claude 3.5 Sonnet (Análisis técnico)",
        "zh": "Claude 3.5 Sonnet（技术深度分析）",
    },
    "model_claude_35_haiku": {
        "en": "Claude 3.5 Haiku (Rapid Extraction)",
        "de": "Claude 3.5 Haiku (Schnelle Extraktion)",
        "fr": "Claude 3.5 Haiku (Extraction rapide)",
        "es": "Claude 3.5 Haiku (Extracción rápida)",
        "zh": "Claude 3.5 Haiku（极速信息提取）",
    },
    "model_gpt_4o": {
        "en": "GPT-4o (Omnimodal Processing)",
        "de": "GPT-4o (Omnimodale Verarbeitung)",
        "fr": "GPT-4o (Traitement omnimodal)",
        "es": "GPT-4o (Procesamiento omnimodal)",
        "zh": "GPT-4o（全模态处理）",
    },
    "model_gpt_4o_mini": {
        "en": "GPT-4o Mini (Fast & Lightweight)",
        "de": "GPT-4o Mini (Schnell & Leichtgewichtig)",
        "fr": "GPT-4o Mini (Rapide & Léger)",
        "es": "GPT-4o Mini (Rápido y ligero)",
        "zh": "GPT-4o Mini（轻量快速）",
    },
    "optgroup_free": {
        "en": "Free Tier Setups",
        "de": "Kostenlose Setups",
        "fr": "Configurations Gratuites",
        "es": "Configuraciones Gratuitas",
        "zh": "免费基础配置",
    },
    "optgroup_premium": {
        "en": "Paid Models (Direct BYOK)",
        "de": "Kostenpflichtige Modelle (Direct BYOK)",
        "fr": "Modèles Payants (Direct BYOK)",
        "es": "Modelos de Pago (Direct BYOK)",
        "zh": "付费商业模型 (Direct BYOK)",
    },
    "model_preset_gemini_max": {
        "en": "Gemini Maximum: Gemini 3.5 Flash (Operational) + Gemini 3.1 Pro (Synthesis)",
        "de": "Gemini Maximum: Gemini 3.5 Flash (Operativ) + Gemini 3.1 Pro (Synthese)",
        "fr": "Gemini Maximum : Gemini 3.5 Flash (Opérationnel) + Gemini 3.1 Pro (Synthèse)",
        "es": "Gemini Máximo: Gemini 3.5 Flash (Operativo) + Gemini 3.1 Pro (Síntesis)",
        "zh": "Gemini 最高配：Gemini 3.5 Flash（实时分块）+ Gemini 3.1 Pro（终极综合）",
    },
    "model_preset_gemini_medium": {
        "en": "Gemini Medium: Gemini 3.5 Flash-Lite (Operational) + Gemini 3.5 Flash (Synthesis)",
        "de": "Gemini Medium: Gemini 3.5 Flash-Lite (Operativ) + Gemini 3.5 Flash (Synthese)",
        "fr": "Gemini Moyen : Gemini 3.5 Flash-Lite (Opérationnel) + Gemini 3.5 Flash (Synthèse)",
        "es": "Gemini Medio: Gemini 3.5 Flash-Lite (Operativo) + Gemini 3.5 Flash (Síntesis)",
        "zh": "Gemini 中配：Gemini 3.5 Flash-Lite（实时分块）+ Gemini 3.5 Flash（终极综合）",
    },
    "model_preset_gemini_min": {
        "en": "Gemini Minimum: Gemini 3.1 Flash-Lite (Operational) + Gemini 3.5 Flash-Lite (Synthesis)",
        "de": "Gemini Minimum: Gemini 3.1 Flash-Lite (Operativ) + Gemini 3.5 Flash-Lite (Synthese)",
        "fr": "Gemini Minimum : Gemini 3.1 Flash-Lite (Opérationnel) + Gemini 3.5 Flash-Lite (Synthèse)",
        "es": "Gemini Mínimo: Gemini 3.1 Flash-Lite (Operativo) + Gemini 3.5 Flash-Lite (Síntesis)",
        "zh": "Gemini 低配：Gemini 3.1 Flash-Lite（实时分块）+ Gemini 3.5 Flash-Lite（终极综合）",
    },
    "model_preset_paid_gemini": {
        "en": "Gemini 3.8 Flash (Operational & Synthesis)",
        "de": "Gemini 3.8 Flash (Operativ & Synthese)",
        "fr": "Gemini 3.8 Flash (Opérationnel & Synthèse)",
        "es": "Gemini 3.8 Flash (Operativo y Síntesis)",
        "zh": "Gemini 3.8 Flash（实时分块与综合）",
    },
    "model_preset_paid_claude": {
        "en": "Claude 5.5 Sonnet (Operational & Synthesis)",
        "de": "Claude 5.5 Sonnet (Operativ & Synthese)",
        "fr": "Claude 5.5 Sonnet (Opérationnel & Synthèse)",
        "es": "Claude 5.5 Sonnet (Operativo y Síntesis)",
        "zh": "Claude 5.5 Sonnet (实时分块与综合)",
    },
    "model_preset_paid_openai": {
        "en": "GPT-6.1 Sol (Operational & Synthesis)",
        "de": "GPT-6.1 Sol (Operativ & Synthese)",
        "fr": "GPT-6.1 Sol (Opérationnel & Synthèse)",
        "es": "GPT-6.1 Sol (Operativo y Síntesis)",
        "zh": "GPT-6.1 Sol (实时分块与综合)",
    },
    "model_preset_gemini_default": {
        "en": "Gemini Maximum: Gemini 3.5 Flash (Operational) + Gemini 3.1 Pro (Synthesis)",
        "de": "Gemini Maximum: Gemini 3.5 Flash (Operativ) + Gemini 3.1 Pro (Synthese)",
        "fr": "Gemini Maximum : Gemini 3.5 Flash (Opérationnel) + Gemini 3.1 Pro (Synthèse)",
        "es": "Gemini Máximo: Gemini 3.5 Flash (Operativo) + Gemini 3.1 Pro (Síntesis)",
        "zh": "Gemini 最高配：Gemini 3.5 Flash（实时分块）+ Gemini 3.1 Pro（终极综合）",
    },
    "model_preset_gemini_eco": {
        "en": "Gemini Medium: Gemini 3.5 Flash-Lite (Operational) + Gemini 3.5 Flash (Synthesis)",
        "de": "Gemini Medium: Gemini 3.5 Flash-Lite (Operativ) + Gemini 3.5 Flash (Synthese)",
        "fr": "Gemini Moyen : Gemini 3.5 Flash-Lite (Opérationnel) + Gemini 3.5 Flash (Synthèse)",
        "es": "Gemini Medio: Gemini 3.5 Flash-Lite (Operativo) + Gemini 3.5 Flash (Síntesis)",
        "zh": "Gemini 中配：Gemini 3.5 Flash-Lite（实时分块）+ Gemini 3.5 Flash（终极综合）",
    },
    "model_preset_premium_claude": {
        "en": "Claude 5.5 Sonnet (Operational & Synthesis)",
        "de": "Claude 5.5 Sonnet (Operativ & Synthese)",
        "fr": "Claude 5.5 Sonnet (Opérationnel & Synthèse)",
        "es": "Claude 5.5 Sonnet (Operativo y Síntesis)",
        "zh": "Claude 5.5 Sonnet (实时分块与综合)",
    },
    "model_preset_premium_openai": {
        "en": "GPT-6.1 Sol (Operational & Synthesis)",
        "de": "GPT-6.1 Sol (Operativ & Synthese)",
        "fr": "GPT-6.1 Sol (Opérationnel & Synthèse)",
        "es": "GPT-6.1 Sol (Operativo y Síntesis)",
        "zh": "GPT-6.1 Sol (实时分块与综合)",
    },
    "model_preset_premium_o3mini": {
        "en": "GPT-6.1 Sol (Operational & Synthesis)",
        "de": "GPT-6.1 Sol (Operativ & Synthese)",
        "fr": "GPT-6.1 Sol (Opérationnel & Synthèse)",
        "es": "GPT-6.1 Sol (Operativo y Síntesis)",
        "zh": "GPT-6.1 Sol (实时分块与综合)",
    },
    "guide_toggle_btn": {
        "en": "How to get your free key (3 steps) ▾",
        "de": "Kostenlosen Schlüssel anfordern (3 Schritte) ▾",
        "fr": "Obtenir votre clé gratuite (3 étapes) ▾",
        "es": "Cómo obtener tu clave gratuita (3 pasos) ▾",
        "zh": "如何获取免费密钥（只需3步）▾",
    },
    "guide_toggle_btn_close": {
        "en": "Hide guide ▴",
        "de": "Leitfaden ausblenden ▴",
        "fr": "Masquer le guide ▴",
        "es": "Ocultar guía ▴",
        "zh": "收起指南 ▴",
    },
    "guide_tag": {
        "en": "100% FREE TO START",
        "de": "100% KOSTENLOS STARTEN",
        "fr": "100 % GRATUIT POUR COMMENCER",
        "es": "100% GRATUITO PARA EMPEZAR",
        "zh": "100% 免费起步",
    },
    "guide_step1_title": {
        "en": "01 / Visit Google AI Studio",
        "de": "01 / Google AI Studio aufrufen",
        "fr": "01 / Accéder à Google AI Studio",
        "es": "01 / Visitar Google AI Studio",
        "zh": "01 / 访问 Google AI Studio",
    },
    "guide_step1_desc": {
        "en": "Open aistudio.google.com and sign in with any Google account. No credit card required.",
        "de": "Öffnen Sie aistudio.google.com und melden Sie sich mit einem Google-Konto an. Keine Kreditkarte erforderlich.",
        "fr": "Ouvrez aistudio.google.com et connectez-vous avec un compte Google. Aucune carte bancaire requise.",
        "es": "Abra aistudio.google.com e inicie sesión con su cuenta de Google. Sin tarjeta de crédito.",
        "zh": "打开 aistudio.google.com 并使用任意 Google 账号登录。无需绑定信用卡。",
    },
    "guide_step2_title": {
        "en": "02 / Create your API Key",
        "de": "02 / API-Schlüssel generieren",
        "fr": "02 / Créer votre clé d'API",
        "es": "02 / Crear tu clave de API",
        "zh": "02 / 创建 API 密钥",
    },
    "guide_step2_desc": {
        "en": "Click 'Get API key' in the sidebar, then select 'Create API key in new project'. Ready instantly.",
        "de": "Klicken Sie auf 'Get API key' und wählen Sie 'Create API key in new project'. Sofort einsatzbereit.",
        "fr": "Cliquez sur 'Get API key' dans la barre latérale, puis 'Create API key in new project'. Prêt instantanément.",
        "es": "Haga clic en 'Get API key' en la barra lateral y luego 'Create API key in new project'. Listo al instante.",
        "zh": "在侧边栏点击 'Get API key'，然后选择 'Create API key in new project' 即可立即生成。",
    },
    "guide_step3_title": {
        "en": "03 / Paste into Chalk",
        "de": "03 / In Chalk einfügen",
        "fr": "03 / Coller dans Chalk",
        "es": "03 / Pegar en Chalk",
        "zh": "03 / 粘贴至 Chalk",
    },
    "guide_step3_desc": {
        "en": "Copy your key string (starting with AIzaSy...) and paste it into Chalk. Ready to synthesize!",
        "de": "Kopieren Sie den Schlüssel (beginnend mit AIzaSy...) und fügen Sie ihn in Chalk ein. Bereit zur Synthese!",
        "fr": "Copiez votre clé (commençant par AIzaSy...) et collez-la dans Chalk. Prêt pour la synthèse !",
        "es": "Copie su clave (comienza con AIzaSy...) y péguela en Chalk. ¡Listo para sintetizar!",
        "zh": "复制密钥（以 AIzaSy... 开头）并粘贴至 Chalk，即可即刻开始实时笔记合成！",
    },
    "guide_action_btn": {
        "en": "Open Google AI Studio ↗",
        "de": "Google AI Studio öffnen ↗",
        "fr": "Ouvrir Google AI Studio ↗",
        "es": "Abrir Google AI Studio ↗",
        "zh": "打开 Google AI Studio ↗",
    },
    "settings_info_banner": {
        "en": "Chalk connects directly from your laptop to the official APIs of the selected provider. No middleman servers, no relays, no telemetry.",
        "de": "Chalk verbindet sich direkt von Ihrem Laptop mit den offiziellen APIs des gewählten Anbieters. Keine Zwischenserver, keine Relays, keine Telemetrie.",
        "fr": "Chalk se connecte directement depuis votre ordinateur aux API officielles du fournisseur choisi. Aucun serveur intermédiaire, aucun relais, aucune télémétrie.",
        "es": "Chalk se conecta directamente desde su equipo a las API oficiales del proveedor seleccionado. Sin servidores intermediarios, sin relés, sin telemetría.",
        "zh": "Chalk 从您的电脑直接连接至所选提供商的官方 API。无中间服务器、无中继、无遥测。",
    },
    "settings_link_aistudio": {
        "en": "Create free Gemini API key at aistudio.google.com →",
        "de": "Kostenlosen Gemini API-Schlüssel bei aistudio.google.com erstellen →",
        "fr": "Créer une clé API Gemini gratuite sur aistudio.google.com →",
        "es": "Crear clave API gratuita de Gemini en aistudio.google.com →",
        "zh": "在 aistudio.google.com 创建免费 Gemini API 密钥 →",
    },
    "settings_tier_notice": {
        "en": "<b>Transparency & Privacy:</b><br>Google AI Studio Free-Tier: Google reserves the right to use prompts for model improvement. For 100% confidential sessions, we recommend a Paid-Tier (Pay-as-you-go) key from Google AI Studio, Anthropic, or OpenAI where data is never used for training.",
        "de": "<b>Transparenz & Datenschutz:</b><br>Google AI Studio Free-Tier: Google behält sich vor, Prompts zur Modellverbesserung zu nutzen. Für 100% vertrauliche Sitzungen empfehlen wir einen Paid-Tier (Pay-as-you-go) Schlüssel von Google AI Studio oder Anthropic/OpenAI, bei dem keine Daten für das Training verwendet werden.",
        "fr": "<b>Transparence et confidentialité :</b><br>Niveau gratuit Google AI Studio : Google se réserve le droit d'utiliser les prompts pour l'entraînement. Pour des sessions 100% confidentielles, nous recommandons une clé payante (Pay-as-you-go) de Google AI Studio, Anthropic ou OpenAI où les données ne sont jamais utilisées pour l'entraînement.",
        "es": "<b>Transparencia y privacidad:</b><br>Nivel gratuito de Google AI Studio: Google se reserva el derecho de usar mensajes para el entrenamiento. Para sesiones 100% confidenciales, recomendamos una clave de pago (Pay-as-you-go) de Google AI Studio, Anthropic u OpenAI donde los datos nunca se utilizan para el entrenamiento.",
        "zh": "<b>透明度与隐私说明：</b><br>Google AI Studio 免费层：Google 保留使用提示词改进模型的权利。对于 100% 保密的学术研讨，我们建议使用 Google AI Studio、Anthropic 或 OpenAI 的付费即用（Pay-as-you-go）密钥，该层级承诺绝不将数据用于模型训练。",
    },
    "settings_gemini_key_label": {
        "en": "Google AI Studio API Key (Gemini):",
        "de": "Google AI Studio API-Schlüssel (Gemini):",
        "fr": "Clé API Google AI Studio (Gemini) :",
        "es": "Clave API de Google AI Studio (Gemini):",
        "zh": "Google AI Studio API 密钥 (Gemini)：",
    },
    "settings_anthropic_key_label": {
        "en": "Anthropic API Key (Optional for Claude 3.7):",
        "de": "Anthropic API-Schlüssel (Optional für Claude 3.7):",
        "fr": "Clé API Anthropic (Optionnel pour Claude 3.7) :",
        "es": "Clave API de Anthropic (Opcional para Claude 3.7):",
        "zh": "Anthropic API 密钥 (Claude 3.7 可选)：",
    },
    "settings_openai_key_label": {
        "en": "OpenAI API Key (Optional for GPT-4o):",
        "de": "OpenAI API-Schlüssel (Optional für GPT-4o):",
        "fr": "Clé API OpenAI (Optionnel pour GPT-4o) :",
        "es": "Clave API de OpenAI (Opcional para GPT-4o):",
        "zh": "OpenAI API 密钥 (GPT-4o 可选)：",
    },
    "settings_vault_label": {
        "en": "Obsidian Vault Directory (Optional for auto-sync):",
        "de": "Obsidian Vault Verzeichnis (Optional für Auto-Sync):",
        "fr": "Répertoire du coffre Obsidian (Optionnel pour auto-sync) :",
        "es": "Directorio de la bóveda de Obsidian (Opcional para auto-sync):",
        "zh": "Obsidian 仓库目录 (可选用于自动同步)：",
    },
    "settings_vault_placeholder": {
        "en": "Path to Obsidian Vault (e.g. ~/Documents/Obsidian)...",
        "de": "Pfad zum Obsidian Vault (z. B. ~/Documents/Obsidian)...",
        "fr": "Chemin du coffre Obsidian (ex. ~/Documents/Obsidian)...",
        "es": "Ruta a la bóveda de Obsidian (ej. ~/Documents/Obsidian)...",
        "zh": "Obsidian 仓库路径 (如 ~/Documents/Obsidian)...",
    },
    "settings_ui_lang_label": {
        "en": "Interface Language (Desktop UI):",
        "de": "Oberflächensprache (Desktop UI):",
        "fr": "Langue de l'interface (Desktop UI) :",
        "es": "Idioma de la interfaz (Desktop UI):",
        "zh": "界面语言 (桌面 UI)：",
    },
    "settings_output_lang_label": {
        "en": "Synthesis Target Language (Notes & Flashcards):",
        "de": "Synthese-Zielsprache (Notizen & Karteikarten):",
        "fr": "Langue cible de synthèse (Notes & Flashcards) :",
        "es": "Idioma de destino de síntesis (Notas y Fichas):",
        "zh": "合成目标语言 (笔记与卡片)：",
    },
    "settings_output_lang_auto": {
        "en": "Auto / Original (Lecture Language)",
        "de": "Auto / Original (Vorlesungssprache)",
        "fr": "Auto / Original (Langue du cours)",
        "es": "Auto / Original (Idioma de la clase)",
        "zh": "自动 / 原始 (保持讲座语言)",
    },
    "settings_status_loaded": {
        "en": "Settings and credentials loaded.",
        "de": "Einstellungen und Schlüssel geladen.",
        "fr": "Paramètres et identifiants chargés.",
        "es": "Configuración y credenciales cargadas.",
        "zh": "设置和凭据已加载。",
    },
    "settings_checking_key": {
        "en": "Validating {provider} API key...",
        "de": "Prüfe {provider} API-Schlüssel...",
        "fr": "Validation de la clé API {provider}...",
        "es": "Validando clave API de {provider}...",
        "zh": "正在验证 {provider} API 密钥...",
    },
    "settings_key_missing": {
        "en": "Please configure an API key for {provider}.",
        "de": "Bitte hinterlegen Sie einen Schlüssel für {provider}.",
        "fr": "Veuillez configurer une clé API pour {provider}.",
        "es": "Por favor configure una clave API para {provider}.",
        "zh": "请为 {provider} 配置 API 密钥。",
    },
    "settings_keyring_saved": {
        "en": "Securely stored in OS Keychain",
        "de": "Sicher im Betriebssystem-Schlüsselbund gespeichert",
        "fr": "Stocké en toute sécurité dans le trousseau de l'OS",
        "es": "Almacenado de forma segura en el llavero del SO",
        "zh": "已安全存储于系统钥匙串",
    },
    "settings_keyring_missing": {
        "en": "Not configured",
        "de": "Nicht konfiguriert",
        "fr": "Non configuré",
        "es": "No configurado",
        "zh": "未配置",
    },
    "preview_key_label": {
        "en": "API Key (BYOK):",
        "de": "API-Schlüssel (BYOK):",
        "fr": "Clé API (BYOK) :",
        "es": "Clave API (BYOK):",
        "zh": "API 密钥 (BYOK)：",
    },

    # ----------------------------------------------------
    # Search Modal
    # ----------------------------------------------------
    "search_dialog_title": {
        "en": "Chalk — Archive & Formula Search [Alt+F]",
        "de": "Chalk — Archiv- & Formelsuche [Alt+F]",
        "fr": "Chalk — Recherche d'archives & formules [Alt+F]",
        "es": "Chalk — Búsqueda de archivos y fórmulas [Alt+F]",
        "zh": "Chalk — 归档与公式搜索 [Alt+F]",
    },
    "search_header_title": {
        "en": "Archive & Formula Search",
        "de": "Archiv- & Formelsuche",
        "fr": "Recherche d'archives et formules",
        "es": "Búsqueda de archivos y fórmulas",
        "zh": "归档与公式搜索",
    },
    "search_hint": {
        "en": "Real-time index across ~/.chalk/sessions/ & Obsidian",
        "de": "Echtzeit-Treffer in ~/.chalk/sessions/ & Obsidian",
        "fr": "Index en temps réel dans ~/.chalk/sessions/ & Obsidian",
        "es": "Índice en tiempo real en ~/.chalk/sessions/ y Obsidian",
        "zh": "实时检索 ~/.chalk/sessions/ 与 Obsidian",
    },
    "search_placeholder": {
        "en": "Search formulas, concepts, theorems, or timestamps (e.g. 'Bayes', 'E=mc^2', '[14:20]')...",
        "de": "Formel, Stichwort, Theorem oder Zeitstempel suchen (z. B. 'Bayes', 'E=mc^2', '[14:20]')...",
        "fr": "Rechercher formules, concepts ou horodatages (ex. 'Bayes', 'E=mc^2', '[14:20]')...",
        "es": "Buscar fórmulas, conceptos o marcas de tiempo (ej. 'Bayes', 'E=mc^2', '[14:20]')...",
        "zh": "搜索公式、概念、定理或时间戳 (如 'Bayes', 'E=mc^2', '[14:20]')...",
    },
    "search_min_chars": {
        "en": "Type at least 2 characters.",
        "de": "Geben Sie mindestens 2 Zeichen ein.",
        "fr": "Tapez au moins 2 caractères.",
        "es": "Escriba al menos 2 caracteres.",
        "zh": "请输入至少 2 个字符。",
    },
    "search_no_results": {
        "en": "No matching notes or formulas found.",
        "de": "Keine passenden Notizen oder Formeln gefunden.",
        "fr": "Aucune note ou formule correspondante trouvée.",
        "es": "No se encontraron notas ni fórmulas coincidentes.",
        "zh": "未找到匹配的笔记或公式。",
    },
    "search_results_found": {
        "en": "{count} matching results found",
        "de": "{count} Treffer gefunden",
        "fr": "{count} résultats trouvés",
        "es": "{count} resultados encontrados",
        "zh": "找到 {count} 条匹配结果",
    },

    # ----------------------------------------------------
    # System Tray
    # ----------------------------------------------------
    "tray_toggle_recording": {
        "en": "Toggle Recording [F9]",
        "de": "Aufnahme umschalten [F9]",
        "fr": "Basculer l'enregistrement [F9]",
        "es": "Alternar grabación [F9]",
        "zh": "切换录音 [F9]",
    },
    "tray_force_flush": {
        "en": "Force Chunk Flush [F10]",
        "de": "Abschnitt synchronisieren [F10]",
        "fr": "Forcer la synchronisation [F10]",
        "es": "Forzar sincronización [F10]",
        "zh": "强制同步分段 [F10]",
    },
    "tray_toggle_hud": {
        "en": "Toggle HUD [Cmd/Ctrl+Shift+Space]",
        "de": "HUD ein-/ausblenden [Cmd/Ctrl+Shift+Space]",
        "fr": "Basculer HUD [Cmd/Ctrl+Shift+Space]",
        "es": "Alternar HUD [Cmd/Ctrl+Shift+Space]",
        "zh": "切换 HUD [Cmd/Ctrl+Shift+Space]",
    },
    "tray_open_obsidian": {
        "en": "Open in Obsidian",
        "de": "In Obsidian öffnen",
        "fr": "Ouvrir dans Obsidian",
        "es": "Abrir en Obsidian",
        "zh": "在 Obsidian 中打开",
    },
    "tray_open_default_editor": {
        "en": "Open in Default Editor",
        "de": "Im Standard-Editor öffnen",
        "fr": "Ouvrir dans l'éditeur système",
        "es": "Abrir en el editor predeterminado",
        "zh": "在默认编辑器中打开",
    },
    "tray_open_notes": {
        "en": "Open Notes Folder",
        "de": "Notizen-Ordner öffnen",
        "fr": "Ouvrir le dossier des notes",
        "es": "Abrir carpeta de notas",
        "zh": "打开笔记文件夹",
    },
    "tray_settings": {
        "en": "Settings (Models & Keys)...",
        "de": "Einstellungen (Modelle & Keys)...",
        "fr": "Paramètres (Modèles & Clés)...",
        "es": "Configuración (Modelos y Claves)...",
        "zh": "设置 (模型与密钥)...",
    },
    "tray_exit": {
        "en": "Quit Chalk",
        "de": "Chalk beenden",
        "fr": "Quitter Chalk",
        "es": "Salir de Chalk",
        "zh": "退出 Chalk",
    },

    # ----------------------------------------------------
    # Desktop Notifications
    # ----------------------------------------------------
    "notify_recording_started_title": {
        "en": "Chalk Active",
        "de": "Chalk Aktiv",
        "fr": "Chalk Actif",
        "es": "Chalk Activo",
        "zh": "Chalk 已激活",
    },
    "notify_recording_started_body": {
        "en": "Recording active: Mic + Loopback + Slides.",
        "de": "Aufnahme aktiv: Mikrofon + Loopback + Folien.",
        "fr": "Enregistrement actif : Micro + Loopback + Diapositives.",
        "es": "Grabación activa: Micrófono + Loopback + Diapositivas.",
        "zh": "录音活跃：麦克风 + 回环 + 幻灯片。",
    },
    "notify_recording_paused_title": {
        "en": "Chalk Paused",
        "de": "Chalk Pausiert",
        "fr": "Chalk en Pause",
        "es": "Chalk Pausado",
        "zh": "Chalk 已暂停",
    },
    "notify_recording_paused_body": {
        "en": "Recording paused.",
        "de": "Aufnahme pausiert.",
        "fr": "Enregistrement en pause.",
        "es": "Grabación pausada.",
        "zh": "录音已暂停。",
    },
    "notify_recording_resumed_title": {
        "en": "Chalk Resumed",
        "de": "Chalk Fortgesetzt",
        "fr": "Chalk Repris",
        "es": "Chalk Reanudado",
        "zh": "Chalk 已恢复",
    },
    "notify_recording_resumed_body": {
        "en": "Recording resumed.",
        "de": "Aufnahme fortgesetzt.",
        "fr": "Enregistrement repris.",
        "es": "Grabación reanudada.",
        "zh": "录音已恢复。",
    },
    "notify_break_detected_title": {
        "en": "Break Detected",
        "de": "Pause erkannt",
        "fr": "Pause détectée",
        "es": "Pausa detectada",
        "zh": "检测到休会",
    },
    "notify_break_detected_body": {
        "en": "Chalk is resting — recording paused until speech resumes.",
        "de": "Chalk pausiert — Aufnahme angehalten bis Sprache fortgesetzt wird.",
        "fr": "Chalk est au repos — enregistrement suspendu jusqu'à la reprise de la parole.",
        "es": "Chalk está en pausa: grabación pausada hasta que se reanude el habla.",
        "zh": "Chalk 正在休息——录音已挂起，直至语音恢复。",
    },
    "notify_speech_resumed_title": {
        "en": "Speech Resumed",
        "de": "Sprache fortgesetzt",
        "fr": "Parole reprise",
        "es": "Habla reanudada",
        "zh": "语音已恢复",
    },
    "notify_speech_resumed_body": {
        "en": "Chalk has resumed active lecture capture.",
        "de": "Chalk hat die aktive Vorlesungsaufzeichnung fortgesetzt.",
        "fr": "Chalk a repris la capture active du cours.",
        "es": "Chalk ha reanudado la captura activa de la clase.",
        "zh": "Chalk 已恢复活跃讲座录制。",
    },
    "notify_master_complete_title": {
        "en": "Chalk Complete",
        "de": "Chalk Abgeschlossen",
        "fr": "Chalk Terminé",
        "es": "Chalk Completado",
        "zh": "Chalk 已完成",
    },
    "notify_master_complete_body": {
        "en": "Master synthesis completed! Opening notes folder.",
        "de": "Master-Synthese abgeschlossen! Notizen-Ordner wird geöffnet.",
        "fr": "Synthèse principale terminée ! Ouverture du dossier des notes.",
        "es": "¡Síntesis maestra completada! Abriendo carpeta de notas.",
        "zh": "主合成已完成！正在打开笔记文件夹。",
    },
    "notify_rate_limit_title": {
        "en": "Chalk Rate Limit",
        "de": "Chalk Rate Limit",
        "fr": "Chalk Limite de Débit",
        "es": "Chalk Límite de Tasa",
        "zh": "Chalk 速率限制",
    },
    "notify_rate_limit_body": {
        "en": "HTTP 429 reached. Backing off 5 min without data loss.",
        "de": "HTTP 429 erreicht. 5-Minuten-Wartezeit aktiv ohne Datenverlust.",
        "fr": "HTTP 429 atteint. Pause de 5 min sans perte de données.",
        "es": "HTTP 429 alcanzado. Pausa de 5 min sin pérdida de datos.",
        "zh": "已达 HTTP 429 速率限制。退避 5 分钟且无数据丢失。",
    },

    # ----------------------------------------------------
    # PDF Exporter
    # ----------------------------------------------------
    "pdf_header_exported": {
        "en": "Exported by Chalk &bull; Ambient Cognitive Presence &bull; Local-First Synthesis Engine",
        "de": "Exportiert von Chalk &bull; Ambientes Kognitives System &bull; Local-First Synthese-Engine",
        "fr": "Exporté par Chalk &bull; Présence cognitive ambiante &bull; Moteur de synthèse Local-First",
        "es": "Exportado por Chalk &bull; Presencia cognitiva ambiental &bull; Motor de síntesis Local-First",
        "zh": "由 Chalk 导出 &bull; 环境感知认知中枢 &bull; 本地优先合成引擎",
    },
    "pdf_default_title": {
        "en": "Chalk Lecture Notes",
        "de": "Chalk Vorlesungsnotizen",
        "fr": "Notes de cours Chalk",
        "es": "Notas de clase de Chalk",
        "zh": "Chalk 讲座笔记",
    },

    # ----------------------------------------------------
    # Recall Debrief
    # ----------------------------------------------------
    "debrief_header": {
        "en": "[ACTIVE RECALL — F9 DEBRIEF]",
        "de": "[AKTIVER ABRUF — F9 DEBRIEF]",
        "fr": "[RAPPEL ACTIF — DÉBRIEFING F9]",
        "es": "[RECUERDO ACTIVO — DEBRIEF F9]",
        "zh": "[主动回忆 — F9 回顾]",
    },
    "debrief_q1": {
        "en": "What is the fundamental invariant or mathematical core assumption of today's lecture?",
        "de": "Was ist die fundamentale Invariante oder mathematische Kernannahme der heutigen Vorlesung?",
        "fr": "Quelle est l'invariant fondamental ou l'hypothèse mathématique centrale du cours d'aujourd'hui ?",
        "es": "¿Cuál es el invariante fundamental o el supuesto matemático central de la clase de hoy?",
        "zh": "今天讲座的基本不变量或核心数学假设是什么？"
    },
    "debrief_q2": {
        "en": "Under which boundary conditions or limits does the derived primary formula lose validity?",
        "de": "Unter welchen Randbedingungen oder Grenzwerten verliert die hergeleitete Hauptformel ihre Gültigkeit?",
        "fr": "Sous quelles conditions aux limites la formule principale dérivée perd-elle sa validité ?",
        "es": "¿Bajo qué condiciones de frontera o límites pierde validez la fórmula principal deducida?",
        "zh": "在哪些边界条件或极限情况下，推导出的主要公式会失效？"
    },
    "debrief_q3": {
        "en": "Which typical modeling or exam misconception was specifically highlighted?",
        "de": "Welcher typische Modellierungs- oder Prüfungsfehler wurde besonders hervorgehoben?",
        "fr": "Quelle erreur classique de modélisation ou d'examen a été particulièrement soulignée ?",
        "es": "¿Qué error típico de modelado o de examen se destacó especialmente?",
        "zh": "特别强调了哪种典型的建模或考试易错点？"
    },
    "preview_chat_grounded": {
        "en": "AI grounded in live audio, slides & photos",
        "de": "KI geerdet in Live-Audio, Folien & Tafelbildern",
        "fr": "IA ancrée dans l'audio, diapositives et photos",
        "es": "IA fundamentada en audio en vivo, diapositivas y fotos",
        "zh": "基于实时音频、幻灯片与白板照片的AI"
    },
    "recording_status": {
        "en": "Recording active",
        "de": "Aufnahme aktiv",
        "fr": "Enregistrement actif",
        "es": "Grabación activa",
        "zh": "录音进行中"
    },
    "tray_hide_hud": {
        "en": "Hide HUD",
        "de": "HUD ausblenden",
        "fr": "Masquer le HUD",
        "es": "Ocultar HUD",
        "zh": "隐藏HUD"
    },
    "audio_slice_playing": {
        "en": "Playing {sec}s audio slice...",
        "de": "Spielt {sec}s Audio-Ausschnitt...",
        "fr": "Lecture de l'extrait audio ({sec}s)...",
        "es": "Reproduciendo fragmento de audio ({sec}s)...",
        "zh": "播放 {sec} 秒音频片段..."
    },
    "session_recovery_title": {
        "en": "Session Recovery",
        "de": "Sitzungswiederherstellung",
        "fr": "Récupération de session",
        "es": "Recuperación de sesión",
        "zh": "会话恢复"
    },
    "session_recovery_detected": {
        "en": "Detected {count} interrupted session(s) with {segments} pending audio segment(s). Preserved in journal.",
        "de": "{count} unterbrochene Sitzung(en) mit {segments} ausstehenden Audio-Segmenten erkannt. Im Journal gesichert.",
        "fr": "{count} session(s) interrompue(s) détectée(s) avec {segments} segment(s) audio en attente. Préservé dans le journal.",
        "es": "Se detectaron {count} sesión(es) interrumpida(s) con {segments} segmento(s) de audio pendientes. Conservado en el diario.",
        "zh": "检测到 {count} 个中断的会话，包含 {segments} 个待处理的音频片段。已保存在日志中。"
    },
    "export_success": {
        "en": "Exported [OK]",
        "de": "Exportiert [OK]",
        "fr": "Exporté [OK]",
        "es": "Exportado [OK]",
        "zh": "导出成功 [OK]"
    },
    "no_flashcards": {
        "en": "No flashcards generated yet",
        "de": "Noch keine Karteikarten generiert",
        "fr": "Aucune carte mémoire générée pour l'instant",
        "es": "Aún no se han generado tarjetas de memoria",
        "zh": "尚未生成抽认卡"
    },
    "notify_auth_error_title": {
        "en": "Chalk: Authentication Error",
        "de": "Chalk: Authentifizierungsfehler",
        "fr": "Chalk : Erreur d'authentification",
        "es": "Chalk: Error de autenticación",
        "zh": "Chalk: 认证错误"
    },
    "notify_auth_error_body": {
        "en": "API key invalid or expired. Check Settings.",
        "de": "API-Schlüssel ungültig oder abgelaufen. Einstellungen prüfen.",
        "fr": "Clé API invalide ou expirée. Vérifiez les Paramètres.",
        "es": "Clave de API no válida o caducada. Compruebe la Configuración.",
        "zh": "API密钥无效或已过期。请检查设置。"
    },
}


class I18nManager:
    """
    Central Internationalization Manager for Chalk Desktop components.
    Provides singleton translation lookup with graceful fallback to English.
    """

    _instance: Optional["I18nManager"] = None

    def __init__(self, default_lang: Optional[str] = None):
        self._current_lang: str = default_lang or config_get_ui_language()
        if self._current_lang not in SUPPORTED_LANGUAGES:
            self._current_lang = "en"

    @classmethod
    def get_instance(cls) -> "I18nManager":
        if cls._instance is None:
            cls._instance = I18nManager()
        return cls._instance

    @property
    def current_language(self) -> str:
        return self._current_lang

    def set_language(self, lang_code: str) -> bool:
        clean = (lang_code or "en").strip().lower()
        if clean in SUPPORTED_LANGUAGES:
            self._current_lang = clean
            config_set_ui_language(clean)
            logger.info("Chalk UI language switched to: %s (%s)", clean, SUPPORTED_LANGUAGES[clean])
            return True
        logger.warning("Unsupported language requested: %s", lang_code)
        return False

    def tr(self, key: str, lang: Optional[str] = None, **kwargs) -> str:
        target_lang = (lang or self._current_lang).strip().lower()
        node = TRANSLATIONS.get(key)
        if not node:
            return key.format(**kwargs) if kwargs else key

        # 1. Target language
        val = node.get(target_lang)
        # 2. English fallback
        if val is None:
            val = node.get("en")
        # 3. Key fallback
        if val is None:
            val = key

        if kwargs:
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return val


# Module-level convenience functions
def get_i18n() -> I18nManager:
    return I18nManager.get_instance()


def tr(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """Translates key using active singleton I18nManager instance."""
    return get_i18n().tr(key, lang=lang, **kwargs)


def get_ui_language() -> str:
    return get_i18n().current_language


def set_ui_language(lang_code: str) -> bool:
    return get_i18n().set_language(lang_code)
