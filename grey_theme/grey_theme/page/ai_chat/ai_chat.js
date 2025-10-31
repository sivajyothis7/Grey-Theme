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
            .addClass('chat-line')
            .css({
                'margin-bottom': '10px',
                'padding': '10px 14px',
                'border-radius': '12px',
                'max-width': '75%',
                'word-wrap': 'break-word',
                'box-shadow': '0 1px 3px rgba(0,0,0,0.1)',
                'background': sender === 'user' ? '#eef2ff' : '#f9f9f9',
                'align-self': sender === 'user' ? 'flex-end' : 'flex-start'
            });

        if (sender === 'bot') {
            const cleaned = formatAIResponse(text);
            msgDiv.html(cleaned);
        } else {
            msgDiv.text(text);
        }

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
                appendMessage(r.message || "No response.", 'bot');
            },
            error: () => {
                $('#' + loadingId).remove();
                appendMessage("⚠️ Something went wrong. Try again.", 'bot');
            }
        });
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

    function formatAIResponse(text) {
        if (!text) return '';

        let cleaned = text
            .replace(/[*_~`]+/g, '')
            .replace(/<br\s*\/?>/gi, '\n')
            .trim();

        const lines = cleaned.split('\n').map(l => l.trim()).filter(Boolean);

        if (lines.length > 1 && lines.some(l => l.includes(':'))) {
            let html = `<table style="width:100%; border-collapse:collapse; font-family:Arial, sans-serif; font-size:14px;">`;
            html += `<thead>
                <tr style="background:#f0f0f0;">
                    <th style="text-align:left; padding:6px 8px; border-bottom:1px solid #ddd;">Response</th>
                    <th style="text-align:right; padding:6px 8px; border-bottom:1px solid #ddd;">Value</th>
                </tr>
            </thead>`;
            html += `<tbody>`;
            lines.forEach(l => {
                const [left, right] = l.split(':');
                if (right) {
                    html += `<tr>
                        <td style="padding:6px 8px; border-bottom:1px solid #f5f5f5;">${left.trim()}</td>
                        <td style="padding:6px 8px; text-align:right; border-bottom:1px solid #f5f5f5;">${right.trim()}</td>
                    </tr>`;
                } else {
                    html += `<tr><td colspan="2" style="padding:6px 8px;">${l}</td></tr>`;
                }
            });
            html += `</tbody></table>`;
            return html;
        }

        cleaned = cleaned
            .split('\n')
            .map(l => `<div style="margin-bottom:4px;">${l}</div>`)
            .join('');

        return cleaned;
    }
};
