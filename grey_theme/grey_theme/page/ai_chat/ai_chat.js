frappe.pages['ai-chat'].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Fateh AI Assistant',
        single_column: true
    });

    $(frappe.render_template("ai_chat", {})).appendTo(page.body);
    let chatSessions = [];
    let activeChat = createNewChat();

    const $chatWindow = $('#ai-chat-window');
    const $chatList = $('#chat-history-list');
    const $userInput = $('#ai-user-input');
    const $sendBtn = $('#ai-send-btn');
    const $newChatBtn = $('#new-chat-btn');

    $sendBtn.on('click', sendMessage);
    $userInput.on('keypress', e => { if (e.which === 13) sendMessage(); });
    $newChatBtn.on('click', startNewChat);
    $(document).on('click', '.suggestion-card', function() {
        const text = $(this).text();
        $userInput.val(text);
        sendMessage();
    });

    function createNewChat() {
        return {
            id: Date.now(),
            title: 'New Chat',
            messages: []
        };
    }

    function renderMessages(chat) {
        $chatWindow.empty();
        chat.messages.forEach(m => appendMessage(m.text, m.sender, false));
    }

    function appendMessage(text, sender, save = true) {
        const msgDiv = $('<div>')
            .addClass('chat-line-wrapper')
            .css({
                'width': '100%',
                'display': 'block',
                'margin-bottom': '12px'
            });

        const bubble = $('<div>')
            .addClass('chat-line')
            .css({
                'padding': '12px 16px',
                'border-radius': '12px',
                'max-width': '80%',
                'word-wrap': 'break-word',
                'background': sender === 'user' ? '#eef2ff' : '#ffffff',
                'align-self': sender === 'user' ? 'flex-end' : 'flex-start',
                'box-shadow': '0 1px 4px rgba(0,0,0,0.06)',
                'display': 'inline-block'
            });

        if (sender === 'bot') {
            if (typeof text === 'object' && text !== null) {
                bubble.text(JSON.stringify(text));
            } else if (String(text).includes("<table") || String(text).includes("<a ") || String(text).includes(".xlsx")) {
                bubble.html(text);
            } else {
                const formatted = formatAIResponse(String(text));
                bubble.html(formatted);
            }
        } else {
            bubble.text(text);
        }

        msgDiv.append(bubble);
        $chatWindow.append(msgDiv);
        $chatWindow.scrollTop($chatWindow[0].scrollHeight);

        if (save) {
            activeChat.messages.push({ sender, text });
            if (activeChat.title === 'New Chat' && sender === 'user') {
                activeChat.title = text.slice(0, 30);
            }
        }
    }

    function sendMessage() {
        const question = $userInput.val().trim();
        if (!question) return;

        appendMessage(question, 'user');
        $userInput.val('');

        const loadingId = 'msg-' + Date.now();
        const loadingMsg = $('<div id="' + loadingId + '" style="font-style:italic; color:#888;">Fateh AI is thinking...</div>');
        $chatWindow.append(loadingMsg);
        $chatWindow.scrollTop($chatWindow[0].scrollHeight);

        frappe.call({
            method: 'grey_theme.chat_handler.handle_ai_query',
            args: { question },
            callback: (r) => {
                $('#' + loadingId).remove();

                const msg = r && r.message ? r.message : null;

                if (msg && typeof msg === 'object' && msg.status) {
                    if (msg.status === 'success') {
                        renderTable(msg);
                    } else if (msg.status === 'empty') {
                        appendMessage("No results found.", 'bot');
                    } else if (msg.status === 'error') {
                        appendMessage("❌ Error: " + (msg.error || "Unknown error"), 'bot');
                    } else {
                        appendMessage(JSON.stringify(msg), 'bot');
                    }
                } else if (typeof msg === 'string') {
                    if (msg.includes("<table") || msg.includes("<a ") || msg.includes(".xlsx")) {
                        appendMessage(msg, 'bot');
                    } else {
                        appendMessage(msg, 'bot');
                    }
                } else {
                    appendMessage("No response.", 'bot');
                }
            },
            error: () => {
                $('#' + loadingId).remove();
                appendMessage("⚠️ Something went wrong. Try again.", 'bot');
            }
        });
    }

    function renderTable(payload) {
        const cols = payload.columns || [];
        const rows = payload.rows || [];
        const excel = payload.excel_url || null;

        let tableHTML = `<div class="ai-table-wrapper" style="overflow:auto;">`;
        tableHTML += `<table class="ai-table" style="width:100%; border-collapse:collapse; font-family:Arial, sans-serif;">`;
        tableHTML += `<thead><tr style="background:#f7f7fb;">`;
        cols.forEach(c => {
            tableHTML += `<th style="text-align:left; padding:8px; border:1px solid #eee;">${escapeHtml(String(c))}</th>`;
        });
        tableHTML += `</tr></thead><tbody>`;

        rows.forEach(r => {
            tableHTML += `<tr>`;
            r.forEach(val => {
                tableHTML += `<td style="padding:8px; border:1px solid #f1f1f1;">${escapeHtml(formatCell(val))}</td>`;
            });
            tableHTML += `</tr>`;
        });

        tableHTML += `</tbody></table></div>`;

        if (excel) {
            tableHTML += `
                <div style="margin-top:12px;">
                    <a href="${escapeAttr(excel)}" target="_blank"
                       style="display:inline-block; background:#3b82f6; color:#fff; padding:8px 12px; border-radius:6px; text-decoration:none; font-weight:600;">
                        📥 Download as Excel
                    </a>
                </div>
            `;
        }

        appendMessage(tableHTML, 'bot');
    }

    function escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function escapeAttr(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/"/g, "%22")
            .replace(/'/g, "%27");
    }

    function formatCell(v) {
        if (v === null || v === undefined) return '';
        if (typeof v === 'number') return v;
        return String(v);
    }

    function formatAIResponse(text) {
        if (!text) return '';

        if (String(text).includes("<table") || String(text).includes("<a ") || String(text).includes(".xlsx")) {
            return String(text);
        }

        let cleaned = String(text).replace(/[*_~`]+/g, '').trim();

        cleaned = cleaned
            .split('\n')
            .map(l => `<div style="margin-bottom:6px;">${escapeHtml(l)}</div>`)
            .join('');

        return cleaned;
    }

    function startNewChat() {
        if (activeChat.messages.length > 0) {
            chatSessions.unshift(activeChat);
            updateChatList();
        }
        activeChat = createNewChat();
        $chatWindow.empty().append(`<div style="font-style:italic; color:#666;">New chat started.</div>`);
    }

    function updateChatList() {
        $chatList.empty();
        chatSessions.forEach(c => {
            const li = $('<li>')
                .css({
                    'display': 'flex',
                    'justify-content': 'space-between',
                    'align-items': 'center',
                    'padding': '8px 10px',
                    'border-radius': '6px',
                    'cursor': 'pointer'
                });

            const title = $('<span>')
                .text(c.title)
                .on('click', () => loadChat(c.id));

            const del = $('<span>')
                .html('🗑')
                .css({ 'cursor': 'pointer', 'margin-left': '8px' })
                .on('click', (e) => {
                    e.stopPropagation();
                    deleteChat(c.id);
                });

            li.append(title).append(del);
            li.hover(() => li.css('background', '#eceeff'), () => li.css('background', 'transparent'));
            $chatList.append(li);
        });
    }

    function deleteChat(id) {
        chatSessions = chatSessions.filter(c => c.id !== id);
        updateChatList();
    }

    function loadChat(id) {
        const chat = chatSessions.find(c => c.id === id);
        if (!chat) return;
        activeChat = chat;
        renderMessages(chat);
    }

    $chatWindow.empty().append(`<div style="font-style:italic; color:#666;">New chat ready — ask me anything.</div>`);
};
