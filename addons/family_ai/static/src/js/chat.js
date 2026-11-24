/** @odoo-module **/

import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";

const MODEL = "family.ai.chat";
// Anything (e.g. the Home card's "Спросить помощника") can open the chat with
// env.bus.trigger(OPEN_CHAT_EVENT).
export const OPEN_CHAT_EVENT = "FAMILY_AI:OPEN_CHAT";

const EXAMPLES = [
    "Что у нас есть сладкого?",
    "Сколько белка мне осталось сегодня?",
    "Сколько мы потратили на рестораны в этом месяце?",
    "Что есть на ужин с высоким белком?",
];

// The chat itself: a sheet over the lower part of the screen.
export class FamilyChatPanel extends Component {
    static template = "family_ai.ChatPanel";
    static props = { close: Function };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.listRef = useRef("list");
        this.inputRef = useRef("input");
        this.panelRef = useRef("panel");
        this.examples = EXAMPLES;
        this.state = useState({ messages: [], text: "", sending: false, configured: true, loaded: false });
        onWillStart(async () => {
            const data = await this.orm.call(MODEL, "get_chat", []);
            this.state.messages = data.messages;
            this.state.configured = data.configured;
            this.state.loaded = true;
        });
        onMounted(() => {
            this.scrollDown();
            this.followKeyboard();
        });
        onPatched(() => this.scrollDown());
        onWillUnmount(() => this.stopFollowingKeyboard());
    }

    // iOS keeps fixed elements at the bottom of the *layout* viewport, i.e. behind the keyboard.
    // Lift the sheet by the keyboard's height (and cap it to what is visible) while it is open.
    followKeyboard() {
        const vv = window.visualViewport;
        if (!vv) {
            return;
        }
        this.onViewport = () => {
            const el = this.panelRef.el;
            if (!el) {
                return;
            }
            const keyboard = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
            el.style.setProperty("--fam-ai-keyboard", `${keyboard}px`);
            el.style.setProperty("--fam-ai-visible", `${vv.height}px`);
            this.scrollDown();
        };
        vv.addEventListener("resize", this.onViewport);
        vv.addEventListener("scroll", this.onViewport);
        this.onViewport();
    }

    stopFollowingKeyboard() {
        const vv = window.visualViewport;
        if (vv && this.onViewport) {
            vv.removeEventListener("resize", this.onViewport);
            vv.removeEventListener("scroll", this.onViewport);
        }
    }

    scrollDown() {
        const el = this.listRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    onInput(ev) {
        this.state.text = ev.target.value;
        // Grow with the text, up to the CSS max-height.
        ev.target.style.height = "auto";
        ev.target.style.height = `${ev.target.scrollHeight}px`;
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
            this.inputRef.el.style.height = "";
        }
        // Show the question right away, with a "typing" bubble until the answer arrives.
        this.state.messages = [...this.state.messages, { role: "user", text: question }];
        this.state.sending = true;
        try {
            const result = await this.orm.call(MODEL, "send", [question]);
            this.state.messages = result.messages;
            if (result.changed) {
                this.notification.add("Shopping List обновлён", { type: "success" });
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

// Round button with Claude's mark, bottom-right over every screen; opens the chat sheet.
export class FamilyChatFab extends Component {
    static template = "family_ai.ChatFab";
    static components = { FamilyChatPanel };
    static props = {};

    setup() {
        this.state = useState({ open: false });
        useBus(this.env.bus, OPEN_CHAT_EVENT, () => this.open());
    }

    open() {
        this.state.open = true;
    }

    close() {
        this.state.open = false;
    }
}

registry.category("main_components").add("FamilyChatFab", { Component: FamilyChatFab });
