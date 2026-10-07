const I18N_STORAGE_KEY = "itemtrace.locale";
const I18N_DEFAULT_LOCALE = "zh-TW";

const I18N_TRANSLATIONS = {
  "zh-TW": {
    "common.save": "儲存",
    "common.cancel": "取消",
    "common.close": "關閉",
    "common.loading": "載入中…",
    "common.retry": "再試一次",
    "common.read_failed": "讀取失敗：{message}",
    "common.back": "返回",
    "common.none": "—",
    "common.photo_count": "{count} 張照片",
    "common.unreadable": "無法讀取檔案\n{filename}",
    "common.unreadable_short": "無法讀取",
    "common.source_photo_alt": "來源照片",
    "common.list_separator": "、",
    "common.plus": "＋",
    "nav.inbox": "Inbox",
    "nav.items": "商品",
    "nav.item_detail": "返回",
    "nav.templates": "Template",
    "nav.settings": "設定",
    "nav.capture": "連續拍照",
    "lang.label": "語言",
    "lang.zh_tw": "繁體中文",
    "lang.en": "English",
    "lang.switch_error": "切換語言失敗：{message}",
    "page.title_inbox": "Inbox · ItemTrace",
    "page.title_items": "商品 · ItemTrace",
    "page.title_item": "商品 · ItemTrace",
    "page.title_capture": "連續拍照 · ItemTrace",
    "page.title_settings": "設定 · ItemTrace",
    "page.title_printing": "列印設定 · ItemTrace",
    "page.title_templates": "Template 管理 · ItemTrace",
    "item.title": "商品",
    "item.name_label": "名稱",
    "item.brand_label": "品牌",
    "item.model_label": "規格／型號",
    "item.category_label": "類型",
    "item.quantity_label": "數量",
    "item.condition_label": "狀態",
    "item.notes_label": "備註",
    "item.item_status_label": "商品狀態",
    "item.item_status_prefix": "商品狀態：",
    "item.attributes_label": "其他屬性",
    "item.model_placeholder": "型號、尺寸、容量、版本、SKU…",
    "item.category_placeholder": "例如：處理器、容器、五金、工具",
    "item.condition_placeholder": "例如：全新、未使用、外觀良好、待檢查",
    "item.data_title": "商品資料",
    "item.data_hint": "這些欄位適用於任何實體物品，不限電子產品。欄位名是資料庫的固定內部名稱（model、category、condition），顯示文字才是給人看的。",
    "item.photos_title": "照片 {count}",
    "item.no_photos": "還沒有照片",
    "item.photo_alt": "照片",
    "item.photo_ai_analyze": "AI 自動填入",
    "item.not_found": "找不到這件商品，可能編號打錯了。",
    "item.updated_at": "更新於 {time}",
    "item.saved": "已儲存",
    "item.save_failed": "儲存失敗：{message}",
    "item.saved_history_failed": "欄位已儲存，但修改歷史載入失敗（{message}）。",
    "item.realtime_note": "識別碼、觀測紀錄與修改歷史在下方。",
    "item.photo_count_suffix": "（{count}）",
    "item.angle_bracket": "[{angle}]",
    "item.detail_load_failed": "載入失敗：{message}",
    "item.events_load_failed": "載入變更歷史失敗：{message}",
    "identifier.title": "識別碼",
    "identifier.kind": "種類",
    "identifier.value": "值",
    "identifier.empty": "還沒有識別碼",
    "identifier.no_source_photo": "沒有來源照片",
    "identifier.confidence": "信心 {value}",
    "identifier.from_suggestion": " · 來自建議",
    "identifier.collision": "⚠ 衝突：",
    "identifier.collision_also": " 也有此識別碼",
    "identifier.view_source": "看來源照片",
    "identifier.kind.serial": "序號",
    "identifier.kind.imei": "IMEI",
    "identifier.kind.barcode": "條碼",
    "identifier.kind.custom": "識別碼",
    "observation.title": "觀測紀錄",
    "observation.number": "編號",
    "observation.kind": "種類",
    "observation.time": "時間",
    "observation.photos": "照片",
    "observation.empty": "還沒有觀測紀錄",
    "observation.kind.intake": "首次觀測",
    "observation.kind.recheck": "複查",
    "observation.kind.manual": "手動",
    "event.title": "修改歷史",
    "event.count": "{count}",
    "event.empty": "無事件",
    "event.revert": "復原",
    "event.revert_failed": "復原失敗：{message}",
    "event.revert_ok_reload_failed": "復原成功，但重新載入失敗（{message}）。畫面可能不是最新狀態，請重新整理確認。",
    "event.type.item_created": "商品已建立",
    "event.type.field_changed": "欄位變更",
    "event.type.observation_created": "觀測紀錄已建立",
    "event.type.photo_created": "照片已建立",
    "event.type.photo_deleted": "照片已刪除",
    "event.type.identifier_created": "識別碼已建立",
    "event.type.identifier_deleted": "識別碼已刪除",
    "event.type.suggestion_created": "建議已建立",
    "event.type.suggestion_accepted": "建議已接受",
    "event.type.suggestion_rejected": "建議已拒絕",
    "event.type.template_created": "範本已建立",
    "event.type.template_updated": "範本已更新",
    "event.type.template_deleted": "範本已刪除",
    "event.actor.user": "使用者",
    "event.actor.external": "外部",
    "event.actor.system": "系統",
    "event.entity.item": "商品",
    "event.entity.identifier": "識別碼",
    "event.entity.photo": "照片",
    "event.entity.observation": "觀測",
    "event.entity.suggestion": "建議",
    "event.entity.template": "範本",
    "suggestion.pending_title": "待確認建議",
    "suggestion.pending_count": "（{pending} 筆待確認，{decided} 筆已決定）",
    "suggestion.pending_count_only": "（{pending} 筆待確認）",
    "suggestion.accept": "接受",
    "suggestion.reject": "拒絕",
    "suggestion.no_source_photo": "沒有來源照片",
    "suggestion.will_create_identifier": "接受後會建立識別碼",
    "suggestion.accept_failed": "接受失敗：{message}",
    "suggestion.reject_failed": "拒絕失敗：{message}",
    "suggestion.accept_ok_reload_failed": "接受成功，但重新載入失敗（{message}）。畫面可能不是最新狀態，請重新整理確認。",
    "suggestion.reject_ok_reload_failed": "拒絕成功，但重新載入失敗（{message}）。畫面可能不是最新狀態，請重新整理確認。",
    "suggestion.ai_analyzing": "分析中…",
    "suggestion.ai_done": "分析完成：共 {count} 筆待確認建議",
    "suggestion.ai_none": "分析完成：模型未傳回任何建議",
    "suggestion.ai_failed": "AI 分析失敗：{message}",
    "suggestion.ai_status": "AI 狀態",
    "items.title": "商品",
    "items.search_placeholder": "搜尋：名稱、品牌、規格、序號後半段…",
    "items.filter_item_status": "全部商品狀態",
    "items.filter_type": "全部類型",
    "items.empty": "沒有符合的商品",
    "items.untitled": "（未填名稱）",
    "items.no_photo": "無照片",
    "items.prev": "上一頁",
    "items.next": "下一頁",
    "items.page_info": "第 {page} 頁",
    "items.range_info": "第 {from}–{to} 筆",
    "items.load_failed": "讀取失敗：{message}",
    "status.active": "使用中",
    "status.archived": "已封存",
    "status.void": "作廢",
    "inbox.title": "Inbox",
    "inbox.capture_hint": "手機相機直接開，拍完一張接一張，最後一次建檔",
    "inbox.empty_line1": "inbox 是空的。",
    "inbox.empty_line2": "從手機相簿選幾張照片丟進來。",
    "inbox.gap_minutes_10": "10 分鐘",
    "inbox.gap_minutes_30": "30 分鐘",
    "inbox.gap_minutes_60": "1 小時",
    "inbox.gap_hours_3": "3 小時",
    "inbox.ungrouped_hint": "這些照片的時間讀不出來（EXIF、檔名都沒有），沒辦法自動分組。整批會建成同一件商品 —— 確認它們本來就是同一件再用。",
    "inbox.build_hint": "選一組照片開始建檔",
    "inbox.build_hint_detail": "建檔後商品欄位會先留空，照片與紀錄會立刻進去，細節到商品頁再補。",
    "inbox.dropzone_title": "點這裡選照片",
    "inbox.dropzone_hint": "可以一次選多張。照片先放進 inbox，還不會建立商品。",
    "inbox.empty": "inbox 是空的。從手機相簿選幾張照片丟進來。",
    "inbox.group_title": "依拍攝時間分組",
    "inbox.gap_label": "間隔",
    "inbox.group_minutes": "{minutes} 分鐘",
    "inbox.group_hours": "{hours} 小時",
    "inbox.group_same_day": "同一天",
    "inbox.group_photo_count": "{count} 張照片",
    "inbox.group_no_time": "時間讀不出來",
    "inbox.pending_count": "{count} 張待處理",
    "inbox.ungrouped_title": "沒有拍攝時間",
    "inbox.ungrouped_count": "（{count} 張）",
    "inbox.selected_prompt": "已選 {count} 張，開始建檔？",
    "inbox.start_intake": "開始建檔",
    "inbox.intaking": "建檔中…",
    "inbox.uploading": "上傳中…（{count} 張）",
    "inbox.upload_done": "上傳完成",
    "inbox.upload_failed": "上傳失敗：{message}",
    "inbox.upload_ok_reload_failed": "上傳成功，但重新載入待處理清單失敗（{message}）。照片已經在 inbox 裡，請重新整理確認。",
    "inbox.intake_failed": "建檔失敗（資料沒有半套）：{message}",
    "inbox.group_failed": "分組失敗：{message}",
    "inbox.load_failed": "讀取失敗：{message}",
    "capture.title": "連續拍照",
    "capture.shutter": "拍照",
    "capture.shutter_hint": "直接開啟相機，拍完可以繼續拍",
    "capture.taken_count": "已拍 {count} 張",
    "capture.taken_count_zero": "已拍 0 張",
    "capture.build_hint": "按「建檔」後這一批照片會一起進入既有的多照片建檔流程：先建立商品，再由 AI 辨識、自動填入商品資料，結果是待確認建議，逐筆接受才會寫進商品。",
    "capture.finish": "完成",
    "capture.continue": "繼續拍攝",
    "capture.discard": "取消整批",
    "capture.build": "建檔",
    "capture.preview_title": "本批照片",
    "capture.grid_empty": "這一批沒有照片了",
    "capture.remove_photo": "移除這張照片",
    "capture.photo_count": "（{count} 張）",
    "capture.missing_after_upload": "上傳後找不到這批照片，請檢查 Inbox",
    "capture.build_failed": "建檔失敗：照片仍在 Inbox 內（{message}），請至 Inbox 重試",
    "settings.title": "設定",
    "settings.language_title": "語言",
    "settings.language_hint": "選擇後立刻套用，並記住這台裝置的選擇。",
    "settings.lan_warning_title": "你正在區網環境。",
    "settings.lan_warning_body": "設定變更會影響所有裝置。API key 只會存在這台電腦的設定檔（已加入 .gitignore），任何 API 回應都不會回傳它。",
    "settings.provider_custom": "Custom（任何 OpenAI 相容 API）",
    "settings.provider_hint": "Google Gemini 與 OpenRouter 都有 OpenAI 相容端點，差別只在 Base URL 與 API key。",
    "settings.base_url_hint": "OpenAI 相容 API 的端點基址。選 Google Gemini 或 OpenRouter 會自動帶入預設值；選 Custom 請自己填該服務的端點。",
    "settings.api_key_hint": "留空不會清除已設定的 key。要清除請按下方「清除 API Key」。",
    "settings.model_hint": "要自己確認過的模型 ID。adapter 不會自動換模型。",
    "settings.next_title": "接下來",
    "settings.next_body": "設定好之後，在商品頁按「AI 自動填入」，或用命令列執行 AI adapter，照片會變成待確認建議，要逐筆看過、按接受才會寫進商品資料。",
    "settings.config_file_body": "設定存在本機的設定檔（已加入 .gitignore，不會被 commit）。這個頁面只是它的一個前端。",
    "settings.ai_title": "AI 設定",
    "settings.ai_intro": "AI 服務連線設定。設定檔存於本機，API key 不會顯示於螢幕或傳送至瀏覽器。",
    "settings.api_key_label": "API Key",
    "settings.api_key_placeholder": "貼上 API key（只寫入本機設定檔）",
    "settings.api_key_set": "API Key：已設定（內容不會顯示）",
    "settings.api_key_unset": "API Key：未設定",
    "settings.provider_label": "Provider",
    "settings.base_url_label": "Base URL",
    "settings.model_label": "Model",
    "settings.save": "儲存",
    "settings.test": "測試 API",
    "settings.clear_key": "清除 API Key",
    "settings.show": "顯示",
    "settings.hide": "隱藏",
    "settings.readonly_placeholder": "僅限本機編輯",
    "settings.readonly_title": "僅限本機編輯",
    "settings.load_failed": "讀取設定失敗：{message}",
    "settings.save_failed": "儲存失敗：{message}",
    "settings.saving": "儲存中…",
    "settings.saved": "設定已儲存",
    "settings.saved_key": "API key 已更新",
    "settings.saved_model": "model 已更新",
    "settings.saved_provider": "provider 已更新",
    "settings.saved_base_url": "base URL 已更新",
    "settings.testing": "測試中…（會送出一次最小請求）",
    "settings.test_ok": "API 測試成功（model {model}）",
    "settings.test_failed": "API 測試失敗：{message}",
    "settings.clear_confirm": "確定要清除 API Key 嗎？\n\n清除後 AI adapter 就不能用了，需要重新貼上 key 才能使用。Provider、Base URL 與 Model 會保留。",
    "settings.clear_done": "API Key 已清除",
    "settings.clear_failed": "清除失敗：{message}",
    "settings.lan_warning": "你正從區網連線。基於安全考量，API key 僅限本機編輯；其他裝置僅可檢視。",
    "settings.config_file": "設定檔：",
    "printing.title": "列印設定",
    "printing.settings_title": "列印設定",
    "printing.settings_intro": "商品頁按「列印」時，會先用這裡的預設值。印表機來自這台電腦（跑 server 的那台），不是手機自己的。",
    "printing.default_printer": "預設印表機",
    "printing.default_template": "預設範本",
    "printing.save": "儲存",
    "printing.try_print": "試印…",
    "printing.saved": "已儲存列印設定",
    "printing.save_failed": "儲存失敗：{message}",
    "printing.config_error": "設定檔有問題：{message}",
    "printing.no_printers": "找不到 Windows 印表機。",
    "printing.printer_list_failed": "讀取印表機清單失敗：{message}",
    "printing.no_printer_option": "（找不到印表機）",
    "printing.printer_read_failed_option": "（印表機不可用）",
    "printing.no_template_option": "（尚無範本可用）",
    "printing.no_item_option": "（無商品）",
    "printing.no_item_name": "（未填名稱）",
    "printing.load_failed": "載入失敗：{message}",
    "template.manager_title": "範本管理",
    "template.column_id": "ID",
    "template.column_name": "名稱",
    "template.column_width": "寬",
    "template.column_height": "高",
    "template.column_created": "建立時間",
    "template.column_updated": "更新時間",
    "template.column_actions": "",
    "template.action_preview": "預覽",
    "template.action_edit": "編輯",
    "template.action_delete": "刪除",
    "template.create_title": "新增範本",
    "template.name_label": "名稱",
    "template.html_label": "HTML",
    "template.width_label": "寬度",
    "template.height_label": "高度",
    "template.unit_label": "單位",
    "template.mm_hint": "尺寸欄留空就用範本自己 CSS 裡的 @page；填了就以這裡為準（列印時會覆蓋範本自訂的 @page）。",
    "template.create": "新增範本",
    "template.create_needs_name": "請填寫名稱並貼上 HTML",
    "template.created": "已建立範本",
    "template.create_failed": "無法建立範本：{message}",
    "template.updated": "範本已更新",
    "template.update_failed": "無法更新範本：{message}",
    "template.deleted": "範本已刪除",
    "template.delete_failed": "無法刪除範本：{message}",
    "template.delete_confirm": "確定要刪除範本 {id} 嗎？此操作無法復原。",
    "template.edit_title": "編輯範本",
    "template.edit_save": "儲存變更",
    "template.edit_cancel": "取消",
    "template.empty": "尚無範本。請從下方表單新增。",
    "template.preview_title": "範本預覽",
    "template.preview_item_label": "商品",
    "template.preview_empty": "尚無商品，無可預覽內容。",
    "template.preview_failed": "預覽失敗：{message}",
    "template.dimensions": "{width}×{height} {unit}",
    "print.action": "列印…",
    "print.title": "列印",
    "print.close": "關閉",
    "print.item_label": "商品",
    "print.template_label": "範本",
    "print.printer_label": "印表機",
    "print.preview": "列印預覽",
    "print.submit": "列印 1 份",
    "print.submitting": "列印中…",
    "print.sending": "正在傳送列印工作…",
    "print.refreshing": "更新預覽中…",
    "print.size": "輸出尺寸 {width} × {height} mm",
    "print.sent": "已送出 1 份到 {printer}｜{width} × {height} mm",
    "print.settings_failed": "讀取列印設定失敗（使用預設值）：{message}",
    "print.templates_failed": "載入範本清單失敗：{message}",
    "print.printers_failed": "讀取印表機清單失敗：{message}",
    "print.preview_failed": "載入列印預覽失敗：{message}",
    "print.submit_failed": "列印失敗：{message}",
    "print.need_selection": "請先選擇商品與範本。",
    "print.no_template": "無可用範本。請先至「設定 → 列印」新增。",
    "print.no_printer": "找不到 Windows 印表機。請先在 Windows 新增印表機。",
    "print.printer_is_default_suffix": "（Windows 預設）",
    "print.printer_note": "印表機由這台電腦（server 主機）管理，不是手機的。",
    "print.manage_link": "需要新增或修改範本請到「設定 → 列印 → 範本管理」。",
    "templates.moved_title": "Template 管理已移到「設定 → 列印」",
    "templates.moved_body": "範本的新增、編輯、預覽與移除，現在都在那一頁；商品頁的列印對話框也與它共用同一段程式。這個網址只是轉頁，Template 的資料沒有變動。",
    "templates.go_to_printing": "前往設定 → 列印",
    "templates.back_to_items": "回到商品列表",
    "showcase.title": "UI Showcase · ItemTrace",
    "showcase.subtitle": "本頁集中展示 ItemTrace 目前實際使用的 UI 元件與狀態。切換語言後所有 UI 標籤應跟著變化，資料內容不翻譯。",
    "showcase.typography": "Typography",
    "showcase.buttons": "Buttons",
    "showcase.delete": "刪除",
    "showcase.forms": "Form Controls",
    "showcase.cards": "Cards / Panels",
    "showcase.status": "Status / Badges",
    "showcase.alerts": "Alerts / Messages",
    "showcase.photos": "Photo / Media",
    "showcase.tables": "Tables",
    "showcase.history": "History / Event",
    "showcase.suggestions": "Suggestion Card",
    "showcase.dialog": "Dialog",
    "showcase.open_dialog": "開啟對話",
    "showcase.open_print": "開啟列印對話",
    "showcase.long_button": "這是一個故意超長的按鈕文字，用來測試 390px 時的換行與溢出",
    "showcase.print_dialog": "Print Dialog",
    "showcase.loading": "Loading / Empty / Error",
    "showcase.notes": "Notes / 已知問題",
    "showcase.long_text": "Long Text / Extreme Cases",
    "showcase.id_long": "ITM-10000",
    "evidence.export": "匯出證據",
    "evidence.exporting": "匯出中…",
    "evidence.exported": "已匯出",
    "evidence.export_failed": "匯出失敗：{message}",
    "evidence.subtitle": "產生單一商品的完整證據 bundle（read-only）",
    "evidence.download": "下載 manifest",
    "evidence.item_label": "商品",
    "evidence.generated_at": "產生時間",
    "evidence.file_count": "檔案數",
    "evidence.photo_count": "照片數",
  },

"en": {
    "common.save": "Save",
    "common.cancel": "Cancel",
    "common.close": "Close",
    "common.loading": "Loading…",
    "common.retry": "Try again",
    "common.read_failed": "Failed to read: {message}",
    "common.back": "Back",
    "common.none": "—",
    "common.photo_count": "{count} photos",
    "common.unreadable": "Cannot read file\n{filename}",
    "common.unreadable_short": "Unreadable",
    "common.source_photo_alt": "Source photo",
    "common.list_separator": "; ",
    "common.plus": "+",

    "nav.inbox": "Inbox",
    "nav.items": "Items",
    "nav.item_detail": "Back",
    "nav.templates": "Templates",
    "nav.settings": "Settings",
    "nav.capture": "Capture",

    "lang.label": "Language",
    "lang.zh_tw": "繁體中文",
    "lang.en": "English",
    "lang.switch_error": "Failed to switch language: {message}",

    "page.title_inbox": "Inbox · ItemTrace",
    "page.title_items": "Items · ItemTrace",
    "page.title_item": "Item · ItemTrace",
    "page.title_capture": "Capture · ItemTrace",
    "page.title_settings": "Settings · ItemTrace",
    "page.title_printing": "Printing settings · ItemTrace",
    "page.title_templates": "Templates · ItemTrace",

    "item.title": "Item",
    "item.name_label": "Name",
    "item.brand_label": "Brand",
    "item.model_label": "Specification / Model",
    "item.category_label": "Type",
    "item.quantity_label": "Quantity",
    "item.condition_label": "Condition",
    "item.notes_label": "Notes",
    "item.item_status_label": "Item Status",
    "item.item_status_prefix": "Item Status: ",
    "item.attributes_label": "Other attributes",
    "item.model_placeholder": "Model, size, capacity, version, SKU…",
    "item.category_placeholder": "e.g. processor, container, hardware, tools",
    "item.condition_placeholder": "e.g. new, unused, good condition, needs inspection",
    "item.data_title": "Item details",
    "item.data_hint": "These fields fit any physical item, not only electronics. The field names are fixed internal database names (model, category, condition); only the displayed text is for people.",
    "item.photos_title": "Photos {count}",
    "item.no_photos": "No photos yet",
    "item.photo_alt": "Photo",
    "item.photo_ai_analyze": "Fill with AI",
    "item.not_found": "Item not found. The number may be wrong.",
    "item.updated_at": "Updated {time}",
    "item.saved": "Saved",
    "item.save_failed": "Save failed: {message}",
    "item.saved_history_failed": "Fields saved, but the change history failed to load ({message}).",
    "item.realtime_note": "Identifiers, observations and history are below.",
    "item.photo_count_suffix": "({count})",
    "item.angle_bracket": "[{angle}]",
    "item.detail_load_failed": "Failed to load: {message}",
    "item.events_load_failed": "Failed to load the change history: {message}",

    "identifier.title": "Identifiers",
    "identifier.kind": "Kind",
    "identifier.value": "Value",
    "identifier.empty": "No identifiers yet",
    "identifier.no_source_photo": "No source photo",
    "identifier.confidence": "Confidence {value}",
    "identifier.from_suggestion": " · from suggestion",
    "identifier.collision": "⚠ Conflict:",
    "identifier.collision_also": " also has this identifier",
    "identifier.view_source": "View source photo",

    "identifier.kind.serial": "Serial",
    "identifier.kind.imei": "IMEI",
    "identifier.kind.barcode": "Barcode",
    "identifier.kind.custom": "Identifier",

    "observation.title": "Observations",
    "observation.number": "Number",
    "observation.kind": "Kind",
    "observation.time": "Time",
    "observation.photos": "Photos",
    "observation.empty": "No observations yet",
    "observation.kind.intake": "Intake",
    "observation.kind.recheck": "Recheck",
    "observation.kind.manual": "Manual",

    "event.title": "History",
    "event.count": "{count}",
    "event.empty": "No history",
    "event.revert": "Revert",
    "event.revert_failed": "Revert failed: {message}",
    "event.revert_ok_reload_failed": "Revert succeeded, but reloading failed ({message}). The screen may be out of date; refresh to confirm.",
    "event.type.item_created": "Item created",
    "event.type.field_changed": "Field changed",
    "event.type.observation_created": "Observation created",
    "event.type.photo_created": "Photo created",
    "event.type.photo_deleted": "Photo deleted",
    "event.type.identifier_created": "Identifier created",
    "event.type.identifier_deleted": "Identifier deleted",
    "event.type.suggestion_created": "Suggestion created",
    "event.type.suggestion_accepted": "Suggestion accepted",
    "event.type.suggestion_rejected": "Suggestion rejected",
    "event.type.template_created": "Template created",
    "event.type.template_updated": "Template updated",
    "event.type.template_deleted": "Template deleted",
    "event.actor.user": "User",
    "event.actor.external": "External",
    "event.actor.system": "System",
    "event.entity.item": "Item",
    "event.entity.identifier": "Identifier",
    "event.entity.photo": "Photo",
    "event.entity.observation": "Observation",
    "event.entity.suggestion": "Suggestion",
    "event.entity.template": "Template",

    "suggestion.pending_title": "Pending suggestions",
    "suggestion.pending_count": "({pending} pending, {decided} decided)",
    "suggestion.pending_count_only": "({pending} pending)",
    "suggestion.accept": "Accept",
    "suggestion.reject": "Reject",
    "suggestion.no_source_photo": "No source photo",
    "suggestion.will_create_identifier": "Accepting will create an identifier",
    "suggestion.accept_failed": "Accept failed: {message}",
    "suggestion.reject_failed": "Reject failed: {message}",
    "suggestion.accept_ok_reload_failed": "Accepted, but reloading failed ({message}). The screen may be out of date; refresh to confirm.",
    "suggestion.reject_ok_reload_failed": "Rejected, but reloading failed ({message}). The screen may be out of date; refresh to confirm.",
    "suggestion.ai_analyzing": "Analyzing…",
    "suggestion.ai_done": "Analysis done: {count} suggestions to review",
    "suggestion.ai_none": "Analysis done: the model returned no suggestions",
    "suggestion.ai_failed": "AI analysis failed: {message}",
    "suggestion.ai_status": "AI status",

    "items.title": "Items",
    "items.search_placeholder": "Search: name, brand, specification, serial tail…",
    "items.filter_item_status": "All item statuses",
    "items.filter_type": "All types",
    "items.empty": "No matching items",
    "items.untitled": "(no name)",
    "items.no_photo": "No photo",
    "items.prev": "Previous",
    "items.next": "Next",
    "items.page_info": "Page {page}",
    "items.range_info": "{from}–{to}",
    "items.load_failed": "Failed to read: {message}",

    "status.active": "Active",
    "status.archived": "Archived",
    "status.void": "Void",

    "inbox.title": "Inbox",
    "inbox.capture_hint": "Opens the phone camera; keep shooting, then create the item once",
    "inbox.empty_line1": "The inbox is empty.",
    "inbox.empty_line2": "Pick a few photos to get started.",
    "inbox.gap_minutes_10": "10 minutes",
    "inbox.gap_minutes_30": "30 minutes",
    "inbox.gap_minutes_60": "1 hour",
    "inbox.gap_hours_3": "3 hours",
    "inbox.ungrouped_hint": "These photos have no capture time (neither EXIF nor the filename), so they cannot be grouped automatically. The whole batch becomes one item — check that they belong together first.",
    "inbox.build_hint": "Select a group to create the item",
    "inbox.build_hint_detail": "The item's fields start empty; photos and records go in immediately. Fill in the details on the item page.",
    "inbox.dropzone_title": "Tap here to choose photos",
    "inbox.dropzone_hint": "You can select several at once. Photos go to the inbox first; no item is created yet.",
    "inbox.empty": "The inbox is empty. Pick a few photos to start.",
    "inbox.group_title": "Grouped by capture time",
    "inbox.gap_label": "Gap",
    "inbox.group_minutes": "{minutes} minutes",
    "inbox.group_hours": "{hours} hours",
    "inbox.group_same_day": "Same day",
    "inbox.group_photo_count": "{count} photos",
    "inbox.group_no_time": "No capture time",
    "inbox.pending_count": "{count} pending",
    "inbox.ungrouped_title": "No capture time",
    "inbox.ungrouped_count": "({count})",
    "inbox.selected_prompt": "{count} selected. Create the item?",
    "inbox.start_intake": "Create item",
    "inbox.intaking": "Creating…",
    "inbox.uploading": "Uploading… ({count})",
    "inbox.upload_done": "Upload done",
    "inbox.upload_failed": "Upload failed: {message}",
    "inbox.upload_ok_reload_failed": "Upload succeeded, but reloading the pending list failed ({message}). The photos are already in the inbox; refresh to confirm.",
    "inbox.intake_failed": "Create failed (nothing partial was written): {message}",
    "inbox.group_failed": "Grouping failed: {message}",
    "inbox.load_failed": "Failed to read: {message}",

    "capture.title": "Capture",
    "capture.shutter": "Take a photo",
    "capture.shutter_hint": "Opens the camera straight away; keep shooting afterwards",
    "capture.taken_count": "{count} taken",
    "capture.taken_count_zero": "0 taken",
    "capture.build_hint": "Press \"Create item\" and this batch goes through the existing multi-photo flow: the item is created first, then AI recognises the photos and fills in fields as pending suggestions that you accept one by one.",
    "capture.finish": "Done",
    "capture.continue": "Keep shooting",
    "capture.discard": "Discard batch",
    "capture.build": "Create item",
    "capture.preview_title": "This batch",
    "capture.grid_empty": "No photos yet",
    "capture.remove_photo": "Remove this photo",
    "capture.photo_count": "({count})",
    "capture.missing_after_upload": "Could not find this batch after upload; check the Inbox",
    "capture.build_failed": "Create failed: the photos are still in the Inbox ({message}); retry from there",

    "settings.title": "Settings",
    "settings.language_title": "Language",
    "settings.language_hint": "Applies immediately and is remembered for this device.",
    "settings.lan_warning_title": "You are on a LAN address.",
    "settings.lan_warning_body": "Changes here affect every device. The API key stays in a settings file on this machine (git-ignored); no API response ever returns it.",
    "settings.provider_custom": "Custom (any OpenAI-compatible API)",
    "settings.provider_hint": "Google Gemini and OpenRouter both expose OpenAI-compatible endpoints; they differ only in base URL and API key.",
    "settings.base_url_hint": "The base URL of an OpenAI-compatible API. Google Gemini and OpenRouter fill it in for you; for Custom, enter that service's endpoint.",
    "settings.api_key_hint": "Leaving this blank does not clear an existing key. Use \"Clear API Key\" below.",
    "settings.model_hint": "A model ID you have verified. The adapter will not switch models for you.",
    "settings.next_title": "Next",
    "settings.next_body": "Once this is set, press \"Fill with AI\" on an item page (or run the adapter from the command line): photos become pending suggestions that you review one by one and accept before anything is written to the item.",
    "settings.config_file_body": "Settings live in a local file (git-ignored, never committed). This page is just a front end for it.",
    "settings.ai_title": "AI service",
    "settings.ai_intro": "Connection settings for the AI service. The settings file stays on this machine; the API key is never shown on screen or sent to the browser.",
    "settings.api_key_label": "API Key",
    "settings.api_key_placeholder": "Paste an API key (written to the local settings file only)",
    "settings.api_key_set": "API Key: set (the value is never shown)",
    "settings.api_key_unset": "API Key: not set",
    "settings.provider_label": "Provider",
    "settings.base_url_label": "Base URL",
    "settings.model_label": "Model",
    "settings.save": "Save",
    "settings.test": "Test connection",
    "settings.clear_key": "Clear API Key",
    "settings.show": "Show",
    "settings.hide": "Hide",
    "settings.readonly_placeholder": "Editable on this machine only",
    "settings.readonly_title": "Editable on this machine only",
    "settings.load_failed": "Failed to read settings: {message}",
    "settings.save_failed": "Save failed: {message}",
    "settings.saving": "Saving…",
    "settings.saved": "Settings saved",
    "settings.saved_key": "API key updated",
    "settings.saved_model": "model updated",
    "settings.saved_provider": "provider updated",
    "settings.saved_base_url": "base URL updated",
    "settings.testing": "Testing… (sends one minimal request)",
    "settings.test_ok": "API test succeeded (model {model})",
    "settings.test_failed": "API test failed: {message}",
    "settings.clear_confirm": "Clear the API Key?\n\nThe AI adapter will stop working until you paste a key again. Provider, Base URL and Model are kept.",
    "settings.clear_done": "API Key cleared",
    "settings.clear_failed": "Clear failed: {message}",
    "settings.lan_warning": "You are connected from a LAN address. For safety the API key can only be edited on this machine; other devices can only read it.",
    "settings.config_file": "Settings file: ",

    "printing.title": "Printing",
    "printing.settings_title": "Printing settings",
    "printing.settings_intro": "The item page's Print button starts from these defaults. Printers come from the machine running the server, not from your phone.",
    "printing.default_printer": "Default printer",
    "printing.default_template": "Default template",
    "printing.save": "Save",
    "printing.try_print": "Test print…",
    "printing.saved": "Printing settings saved",
    "printing.save_failed": "Save failed: {message}",
    "printing.config_error": "Settings file problem: {message}",
    "printing.no_printers": "No Windows printers found.",
    "printing.printer_list_failed": "Failed to read the printer list: {message}",
    "printing.no_printer_option": "(no printers found)",
    "printing.printer_read_failed_option": "(printers unavailable)",
    "printing.no_template_option": "(no templates available)",
    "printing.no_item_option": "(no items)",
    "printing.no_item_name": "(no name)",
    "printing.load_failed": "Failed to load: {message}",

    "template.manager_title": "Templates",
    "template.column_id": "ID",
    "template.column_name": "Name",
    "template.column_width": "Width",
    "template.column_height": "Height",
    "template.column_created": "Created",
    "template.column_updated": "Updated",
    "template.column_actions": "",
    "template.action_preview": "Preview",
    "template.action_edit": "Edit",
    "template.action_delete": "Delete",
    "template.create_title": "New template",
    "template.name_label": "Name",
    "template.html_label": "HTML",
    "template.width_label": "Width",
    "template.height_label": "Height",
    "template.unit_label": "Unit",
    "template.mm_hint": "Leave the size blank to use the template's own CSS @page. If filled in, these win (they override the template's @page when printing).",
    "template.create": "Create template",
    "template.create_needs_name": "Fill in a name and paste the HTML",
    "template.created": "Template created",
    "template.create_failed": "Could not create the template: {message}",
    "template.updated": "Template updated",
    "template.update_failed": "Could not update the template: {message}",
    "template.deleted": "Template deleted",
    "template.delete_failed": "Could not delete the template: {message}",
    "template.delete_confirm": "Delete template {id}? This cannot be undone.",
    "template.edit_title": "Edit template",
    "template.edit_save": "Save changes",
    "template.edit_cancel": "Cancel",
    "template.empty": "No templates yet. Create one with the form below.",
    "template.preview_title": "Template preview",
    "template.preview_item_label": "Item",
    "template.preview_empty": "No items yet, so there is nothing to preview.",
    "template.preview_failed": "Preview failed: {message}",
    "template.dimensions": "{width}×{height} {unit}",

    "print.action": "Print…",
    "print.title": "Print",
    "print.close": "Close",
    "print.item_label": "Item",
    "print.template_label": "Template",
    "print.printer_label": "Printer",
    "print.preview": "Print preview",
    "print.submit": "Print 1 copy",
    "print.submitting": "Printing…",
    "print.sending": "Sending the print job…",
    "print.refreshing": "Updating preview…",
    "print.size": "Output size {width} × {height} mm",
    "print.sent": "Sent 1 copy to {printer}｜{width} × {height} mm",
    "print.settings_failed": "Failed to read printing settings (using defaults): {message}",
    "print.templates_failed": "Failed to load the template list: {message}",
    "print.printers_failed": "Failed to read the printer list: {message}",
    "print.preview_failed": "Failed to load the print preview: {message}",
    "print.submit_failed": "Print failed: {message}",
    "print.need_selection": "Choose an item and a template first.",
    "print.no_template": "No templates available. Add one under Settings → Printing first.",
    "print.no_printer": "No Windows printers found. Add one in Windows first.",
    "print.printer_is_default_suffix": " (Windows default)",
    "print.printer_note": "Printers are managed by this computer (the server), not your phone.",
    "print.manage_link": "To add or edit templates, go to Settings → Printing.",

    "templates.moved_title": "Template management moved to Settings → Printing",
    "templates.moved_body": "Creating, editing, previewing and removing templates now happen on that page. The item page's print dialog shares the same code. This URL just redirects; no template data changed.",
    "templates.go_to_printing": "Go to Settings → Printing",
    "templates.back_to_items": "Back to items"
,
    "showcase.title": "UI Showcase · ItemTrace",
    "showcase.subtitle": "This page showcases ItemTrace's actual UI components, states and responsive behavior. UI labels switch with language; data content is not translated.",
    "showcase.typography": "Typography",
    "showcase.buttons": "Buttons",
    "showcase.delete": "Delete",
    "showcase.forms": "Form Controls",
    "showcase.cards": "Cards / Panels",
    "showcase.status": "Status / Badges",
    "showcase.alerts": "Alerts / Messages",
    "showcase.photos": "Photo / Media",
    "showcase.tables": "Tables",
    "showcase.history": "History / Event",
    "showcase.suggestions": "Suggestion Card",
    "showcase.dialog": "Dialog",
    "showcase.open_dialog": "Open Dialog",
    "showcase.open_print": "Open Print Dialog",
    "showcase.long_button": "This is an intentionally very long button label to test wrapping and overflow at 390px",
    "showcase.print_dialog": "Print Dialog",
    "showcase.loading": "Loading / Empty / Error",
    "showcase.notes": "Notes / Known Issues",
    "showcase.long_text": "Long Text / Extreme Cases",
    "showcase.id_long": "ITM-10000" ,
    "evidence.export": "Export Evidence",
    "evidence.exporting": "Exporting...",
    "evidence.exported": "Evidence bundle exported",
    "evidence.export_failed": "Export failed: {message}",
    "evidence.subtitle": "Generate a complete read-only evidence bundle for this item.",
    "evidence.download": "Download manifest",
    "evidence.item_label": "Item",
    "evidence.generated_at": "Generated at",
    "evidence.file_count": "Files",
    "evidence.photo_count": "Photos", }
};

/* ---------------------------------------------------------------------
 * 狀態
 * ------------------------------------------------------------------- */

let i18nLocale = I18N_DEFAULT_LOCALE;
const i18nListeners = [];

/* localStorage 在私密瀏覽或被政策禁用時會拋出（Safari 私密模式、
   部分企業環境）。那種情況要能正常運作，只是偏好記不住 ——
   讀寫都包起來，失敗就當沒有偏好。 */
function i18nStorage() {
  try {
    if (typeof localStorage === "undefined" || localStorage === null) return null;
    return localStorage;
  } catch (err) {
    return null;
  }
}

function i18nSupported() {
  return Object.prototype.hasOwnProperty.call(I18N_TRANSLATIONS, i18nLocale);
}

/* 從 localStorage 讀偏好。只認支援的語言：存了 "fr" 或被手改過的
   垃圾值時要安靜地退回預設，而不是顯示半翻的畫面。 */
function i18nDetect() {
  const storage = i18nStorage();
  if (!storage) return I18N_DEFAULT_LOCALE;
  try {
    const stored = storage.getItem(I18N_STORAGE_KEY);
    if (stored && Object.prototype.hasOwnProperty.call(I18N_TRANSLATIONS, stored)) {
      return stored;
    }
  } catch (err) {
    /* 讀不到就用預設 */
  }
  return I18N_DEFAULT_LOCALE;
}

function i18nSetLocale(locale) {
  if (!Object.prototype.hasOwnProperty.call(I18N_TRANSLATIONS, locale)) return false;
  i18nLocale = locale;
  const storage = i18nStorage();
  if (storage) {
    try {
      storage.setItem(I18N_STORAGE_KEY, locale);
    } catch (err) {
      /* 存不了（例如配額滿）不影響本次切換，只是下次開頁面會回到預設 */
    }
  }
  return true;
}

function i18nCurrentLocale() {
  return i18nLocale;
}

function i18nLocales() {
  return Object.keys(I18N_TRANSLATIONS);
}

/* ---------------------------------------------------------------------
 * 翻譯查詢
 * ------------------------------------------------------------------- */

/* 取代 {placeholder}。
   刻意只支援具名 placeholder、不支援 printf 位置參數：UI 訊息都是
   「前綴 + 值 + 後綴」，具名比 %s 好讀也不會在參數順序改動時靜默出錯。 */
function i18nInterpolate(template, params) {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, key) => (
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match
  ));
}

/* 查一個 key。回傳值一定是字串，絕不拋出。
 *
 * 找不到時的 fallback 順序是「現語言 → 預設語言 → key 本身」。第三步
 * 很重要：畫面會顯示 "item.foo_label"，一眼看得出是漏翻的 key，
 * 而不是空白或 undefined。 */
function t(key, params) {
  const current = i18nSupported() ? I18N_TRANSLATIONS[i18nLocale] : null;
  if (current && Object.prototype.hasOwnProperty.call(current, key)) {
    return i18nInterpolate(current[key], params);
  }
  const fallback = I18N_TRANSLATIONS[I18N_DEFAULT_LOCALE];
  if (fallback && Object.prototype.hasOwnProperty.call(fallback, key)) {
    return i18nInterpolate(fallback[key], params);
  }
  /* 連預設語言都沒有 → 這是開發期錯誤，不是使用者能處理的問題。
     用 console.warn 而不是 throw：throw 會讓整頁初始化中斷、畫面變空白，
     那比顯示一個漏翻的 key 糟糕得多。 */
  if (typeof console !== "undefined" && console && console.warn) {
    console.warn("[i18n] missing translation key:", key);
  }
  return key;
}

/* ---------------------------------------------------------------------
 * 依語言格式化時間
 * ------------------------------------------------------------------- */

/* 顯示日期時間，語言跟著畫面走。
   不傳 locale 的話瀏覽器會用作業系統的語言 —— 使用者把介面切成 English
   卻看到「2026/10/5 下午8:17:41」這種半中半英的畫面。時間字串屬於 UI
   （不是商品資料），所以跟著語言走是正確的。 */
function i18nFormatDateTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (isNaN(date.getTime())) return String(iso);
  try {
    return date.toLocaleString(i18nSupported() ? i18nLocale : I18N_DEFAULT_LOCALE);
  } catch (err) {
    /* 極舊的瀏覽器可能不認這個 locale；退回 ISO 片段而不是炸掉 */
    return String(iso).replace("T", " ").slice(0, 16);
  }
}

/* ---------------------------------------------------------------------
 * DOM 套用
 * ------------------------------------------------------------------- */

/* markup 裡用 data-i18n 標記靜態文字：
     <button data-i18n="common.save">儲存</button>
     <input data-i18n-placeholder="item.model_placeholder">
     <div data-i18n-title="...">
   內文預設就是繁體中文，所以沒有 JS 時頁面仍然可讀（漸進增強），
   這也是為什麼 key 不需要當成 fallback 的第一道防線。
   這些 attribute 刻意**不刪除**：重新套用語言時還需要它們。 */
function i18nHas(key, locale) {
  const loc = locale || i18nLocale;
  const current = (Object.prototype.hasOwnProperty.call(I18N_TRANSLATIONS, loc)) ? I18N_TRANSLATIONS[loc] : null;
  if (current && Object.prototype.hasOwnProperty.call(current, key)) return true;
  const fallback = I18N_TRANSLATIONS[I18N_DEFAULT_LOCALE];
  return !!(fallback && Object.prototype.hasOwnProperty.call(fallback, key));
}

function i18nUpdateLangButtons(root) {
  const scope = root || (typeof document === "undefined" ? null : document);
  if (!scope || typeof scope.querySelectorAll !== "function") return;
  const btns = scope.querySelectorAll(".lang-btn[data-lang]");
  Array.prototype.forEach.call(btns, (btn) => {
    if (!btn || typeof btn.getAttribute !== "function") return;
    const lang = btn.getAttribute("data-lang");
    const isActive = lang === i18nLocale;
    if (btn.classList && typeof btn.classList.toggle === "function") {
      btn.classList.toggle("active", isActive);
    }
    if (typeof btn.setAttribute === "function") {
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    }
  });
}

function i18nApply(root) {
  /* 沒有 DOM 就什麼都不做 —— 不要拋。
     i18nApply 會在 i18nInit() 與每次切換語言時被呼叫，而 i18n.js 是每個
     頁面的第一支 script。DOM 還沒就緒或根本不存在（例如頁面載入失敗、
     測試環境）時，靜靜地什麼都不做遠比拋出來安全。 */
  const scope = root || (typeof document === "undefined" ? null : document);
  if (!scope || typeof scope.querySelectorAll !== "function") return;

  const attributes = [
    ["data-i18n", "textContent"],
    ["data-i18n-html", "innerHTML"],
    ["data-i18n-placeholder", "placeholder"],
    ["data-i18n-title", "title"],
    ["data-i18n-aria-label", "aria-label"],
  ];

  attributes.forEach(([attr, property]) => {
    const nodes = scope.querySelectorAll("[" + attr + "]");
    Array.prototype.forEach.call(nodes, (node) => {
      const key = node.getAttribute(attr);
      if (!key) return;
      if (!i18nHas(key)) {
        const cur = node[property];
        if (cur !== undefined && cur !== null && String(cur).trim() !== "") {
          if (typeof console !== "undefined" && console && console.warn) {
            console.warn("[i18n] missing translation key (keeping markup text):", key);
          }
          return;
        }
      }
      const value = t(key);
      /* textContent 對 text node 也安全（node 是 Element 才有）；
         元素沒有 textContent 時不要碰 innerHTML —— 那是 data-i18n-html
         的工作，混在一起會讓純文字的字串被當成 HTML 解析。 */
      if (node[property] !== undefined) node[property] = value;
    });
  });

  i18nUpdateLangButtons(scope);
}

/* 語言改變時呼叫。所有訂閱者都會收到新語言。
   頁面用它重新渲染動態部分（下拉選單的選項文字、錯誤訊息、
   時間格式那些不在 markup 裡的東西）。 */
function i18nSubscribe(callback) {
  if (typeof callback === "function") i18nListeners.push(callback);
}

function i18nNotify() {
  i18nListeners.forEach((callback) => {
    try {
      callback(i18nLocale);
    } catch (err) {
      /* 一個訂閱者壞掉不該讓其他頁面元素停擺 */
      if (typeof console !== "undefined" && console && console.error) {
        console.error("[i18n] locale listener failed:", err);
      }
    }
  });
}

/* 切換語言並重新套用。回傳是否成功（不支援的語言會回 false 且不動作）。 */
function i18nSwitch(locale) {
  if (!i18nSetLocale(locale)) return false;
  i18nApply();
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.setAttribute("lang", locale);
  }
  i18nNotify();
  return true;
}

/* 頁面載入時呼叫一次：讀偏好 → 套用靜態文字 → 通知訂閱者。
   每個頁面的 script 都必須在最後呼叫，順序：i18n 先讀偏好，
   頁面 script 才用 t() 產生動態文字。 */
function i18nInit() {
  i18nSetLocale(i18nDetect());
  i18nApply();
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.setAttribute("lang", i18nLocale);
  }
  return i18nLocale;
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!target || typeof target.closest !== "function") return;
    const btn = target.closest(".lang-btn[data-lang]");
    if (!btn) return;
    const lang = btn.getAttribute("data-lang");
    if (lang && lang !== i18nLocale) {
      i18nSwitch(lang);
    }
  });
}
