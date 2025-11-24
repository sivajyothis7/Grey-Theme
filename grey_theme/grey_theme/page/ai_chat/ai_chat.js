frappe.pages['ai-chat'].on_page_load = function(wrapper) {

    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Fateh AI Assistant",
        single_column: true
    });

    $(frappe.render_template("ai_chat", {})).appendTo(page.body);

    let chatSessions = [];
    let activeChat = createNewChat();

    const $chatWindow = $("#ai-chat-window");
    const $chatList = $("#chat-history-list");
    const $userInput = $("#ai-user-input");
    const $sendBtn = $("#ai-send-btn");
    const $newChatBtn = $("#new-chat-btn");

   

    function applyTheme(theme) {
        const root = document.getElementById("ai-chat-app");
        root.classList.remove("theme-light", "theme-dark");
        root.classList.add(theme);
        localStorage.setItem("fateh_ai_theme", theme);
    }

    function toggleTheme() {
        const current = localStorage.getItem("fateh_ai_theme") || "theme-light";
        const next = current === "theme-light" ? "theme-dark" : "theme-light";
        applyTheme(next);
    }

    const savedTheme = localStorage.getItem("fateh_ai_theme") || "theme-light";
    setTimeout(() => applyTheme(savedTheme), 10);

    $("#theme-toggle-btn").on("click", toggleTheme);



    $sendBtn.on("click", sendMessage);
    $userInput.on("keypress", e => { if (e.which === 13) sendMessage(); });
    $newChatBtn.on("click", startNewChat);

    $(document).on("click", ".shortcut-card", function() {
        const query = $(this).attr("data-q");
        $userInput.val(query);
        sendMessage();
    });


  
    function createNewChat() {
        return { id: Date.now(), title: "New Chat", messages: [] };
    }

    function appendBubble(text, sender, save=true) {
        const wrapper = $("<div>").css({
            display: "flex",
            justifyContent: sender === "user" ? "flex-end" : "flex-start",
            width: "100%",
            marginBottom: "12px"
        });

        const bubble = $("<div>")
            .addClass("chat-bubble")
            .addClass(sender)
            .html(text);

        wrapper.append(bubble);
        $chatWindow.append(wrapper);
        $chatWindow.scrollTop($chatWindow[0].scrollHeight);

        if (save) activeChat.messages.push({ sender, text });
    }

    function sendMessage() {
        const question = $userInput.val().trim();
        if (!question) return;

        appendBubble(question, "user");
        $userInput.val("");

        const loading = $("<div class='chat-bubble bot' style='opacity:0.6;'>Thinking...</div>");
        appendBubble(loading, "bot");

        frappe.call({
            method: "grey_theme.chat_handler.handle_ai_query",
            args: { question },
            callback: (r) => {
                loading.remove();
                renderResponse(r.message);
            },
            error: () => {
                loading.remove();
                appendBubble("⚠️ Something went wrong.", "bot");
            }
        });
    }

    function renderResponse(msg) {
        if (!msg) return appendBubble("No response.", "bot");

        if (typeof msg === "string") return appendBubble(msg, "bot");

        if (msg.status === "success") {
            let html = `<table class="ai-table"><thead><tr>`;
            msg.columns.forEach(c => html += `<th>${c}</th>`);
            html += `</tr></thead><tbody>`;

            msg.rows.forEach(r => {
                html += `<tr>${r.map(v => `<td>${v}</td>`).join("")}</tr>`;
            });

            html += `</tbody></table>`;

            if (msg.excel_url) {
                html += `<a href="${msg.excel_url}" target="_blank" class="excel-download-btn">📥 Download Excel</a>`;
            }

            return appendBubble(html, "bot");
        }

        appendBubble(JSON.stringify(msg), "bot");
    }


   

    function startNewChat() {
        if (activeChat.messages.length > 0) chatSessions.unshift(activeChat);
        activeChat = createNewChat();
        $chatWindow.html(`<div class="chat-placeholder">New chat ready — ask me anything.</div>`);
        updateHistory();
    }

    function updateHistory() {
        $chatList.empty();
        chatSessions.forEach(chat => {
            const li = $("<li>")
                .text(chat.title)
                .css({ cursor: "pointer", padding: "10px" })
                .on("click", () => loadChat(chat.id));

            const del = $("<span>🗑</span>")
                .css({ float: "right", cursor: "pointer" })
                .on("click", e => {
                    e.stopPropagation();
                    deleteChat(chat.id);
                });

            li.append(del);
            $chatList.append(li);
        });
    }

    function deleteChat(id) {
        chatSessions = chatSessions.filter(c => c.id !== id);
        updateHistory();
    }

    function loadChat(id) {
        const chat = chatSessions.find(c => c.id === id);
        if (!chat) return;
        activeChat = chat;

        $chatWindow.empty();
        chat.messages.forEach(msg => appendBubble(msg.text, msg.sender, false));
    }

    $chatWindow.html(`<div class="chat-placeholder">New chat ready — ask me anything.</div>`);
};
