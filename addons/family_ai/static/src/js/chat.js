/** @odoo-module **/

import { Component, onMounted, onPatched, onWillStart, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MODEL = "family.ai.chat";

const EXAMPLES = [
    "Что у нас есть сладкого?",
    "Сколько белка мне осталось сегодня?",
    "Сколько мы потратили на рестораны в этом месяце?",
    "Что есть на ужин с высоким белком?",
];

// The assistant chat: ask about stock, meals, weight or money in plain words.
export class FamilyChatDialog extends Component {
    static template = "family_ai.ChatDialog";
    static components = { Dialog };
    static props = { close: Function };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.listRef = useRef("list");
        this.inputRef = useRef("input");
        this.examples = EXAMPLES;
        this.state = useState({ messages: [], text: "", sending: false, configured: true });
        onWillStart(async () => {
            const data = await this.orm.call(MODEL, "get_chat", []);
            this.state.messages = data.messages;
            this.state.configured = data.configured;
        });
        onMounted(() => this.scrollDown());
        onPatched(() => this.scrollDown());
    }

    scrollDown() {
        const el = this.listRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    onInput(ev) {
        this.state.text = ev.target.value;
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    async send(text) {
        const question = (text ?? this.state.text).trim();
        if (!question || this.state.sending) {
            return;
        }
        this.state.text = "";
        if (this.inputRef.el) {
            this.inputRef.el.value = "";
        }
        // Show the question right away, with a "typing" bubble until the answer arrives.
        this.state.messages = [...this.state.messages, { role: "user", text: question }];
        this.state.sending = true;
        try {
            const result = await this.orm.call(MODEL, "send", [question]);
            this.state.messages = result.messages;
            if (result.changed) {
                this.notification.add("Список покупок обновлён", { type: "success" });
            }
        } catch (error) {
            this.state.messages = [
                ...this.state.messages,
                { role: "assistant", text: "Не получилось отправить. Попробуй ещё раз." },
            ];
            throw error;
        } finally {
            this.state.sending = false;
        }
    }

    async newChat() {
        const data = await this.orm.call(MODEL, "reset_chat", []);
        this.state.messages = data.messages;
    }
}

// Speech-bubble icon in the top bar: the chat is one tap away from every screen.
export class FamilyChatSystray extends Component {
    static template = "family_ai.ChatSystray";
    static props = {};

    setup() {
        this.dialog = useService("dialog");
    }

    open() {
        this.dialog.add(FamilyChatDialog, {});
    }
}

registry.category("systray").add("family_ai.chat", { Component: FamilyChatSystray }, { sequence: 1 });
