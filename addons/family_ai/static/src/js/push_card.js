/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

// Odoo serves its service worker (with mail's push handlers appended) here, scoped to /web.
const SW_URL = "/web/service-worker.js";
const SW_SCOPE = "/web";

function urlBase64ToUint8Array(base64) {
    const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(padded);
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function isIos() {
    return /iPhone|iPad|iPod/.test(navigator.userAgent);
}

function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
}

// "Notifications" card on the Home page: turn push on for this phone, send a test, open the feed.
export class FamilyPushCard extends Component {
    static template = "family_ai.PushCard";
    static props = {};

    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            // unsupported | not_installed | denied | off | on
            status: "off",
            busy: false,
            aiConfigured: true,
            lastText: "",
        });
        onWillStart(() => this.refresh());
    }

    async getSubscription() {
        const registration = await navigator.serviceWorker.getRegistration(SW_SCOPE);
        return registration ? registration.pushManager.getSubscription() : null;
    }

    async refresh() {
        if (!pushSupported()) {
            // iOS only exposes push to apps opened from the home-screen icon (iOS 16.4+).
            this.state.status = isIos() && !isStandalone() ? "not_installed" : "unsupported";
            return;
        }
        if (Notification.permission === "denied") {
            this.state.status = "denied";
            return;
        }
        try {
            const subscription = await this.getSubscription();
            const result = await this.rpc("/family/push/status", {
                endpoint: subscription ? subscription.endpoint : null,
            });
            this.state.aiConfigured = result.ai_configured;
            this.state.status =
                subscription && result.this_device && Notification.permission === "granted" ? "on" : "off";
        } catch {
            this.state.status = "off";
        }
    }

    async enable() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            // First thing in the tap handler: iOS only shows the prompt during a user gesture.
            const permission = await Notification.requestPermission();
            if (permission !== "granted") {
                this.state.status = permission === "denied" ? "denied" : "off";
                return;
            }
            const registration = await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE });
            await navigator.serviceWorker.ready;
            const vapidKey = await this.rpc("/family/push/vapid_key");
            const applicationServerKey = urlBase64ToUint8Array(vapidKey);

            let subscription = await registration.pushManager.getSubscription();
            const previousEndpoint = subscription ? subscription.endpoint : null;
            if (subscription && !this.sameKey(subscription, applicationServerKey)) {
                // Subscribed with an older server key: it would never receive anything.
                await subscription.unsubscribe();
                subscription = null;
            }
            if (!subscription) {
                subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey,
                });
            }
            await this.rpc("/family/push/subscribe", {
                subscription: subscription.toJSON(),
                previous_endpoint: previousEndpoint !== subscription.endpoint ? previousEndpoint : null,
            });
            this.state.status = "on";
            this.notification.add("Уведомления включены на этом телефоне", { type: "success" });
        } catch (error) {
            console.error("family_ai: push subscribe failed", error);
            this.notification.add(`Не получилось включить уведомления: ${error.message || error}`, {
                type: "danger",
            });
        } finally {
            this.state.busy = false;
        }
    }

    sameKey(subscription, key) {
        const current = subscription.options && subscription.options.applicationServerKey;
        if (!current) {
            return true; // the browser does not tell us; assume it is fine
        }
        const bytes = new Uint8Array(current);
        return bytes.length === key.length && bytes.every((b, i) => b === key[i]);
    }

    async disable() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const subscription = await this.getSubscription();
            if (subscription) {
                await this.rpc("/family/push/unsubscribe", { endpoint: subscription.endpoint });
                await subscription.unsubscribe();
            }
            this.state.status = "off";
        } finally {
            this.state.busy = false;
        }
    }

    async sendTest() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.rpc("/family/push/test");
            this.state.lastText = result.text;
            if (!result.pushed) {
                this.notification.add("Сообщение создано, но push не ушёл: на сервере нет этого телефона.", {
                    type: "warning",
                });
            }
        } finally {
            this.state.busy = false;
        }
    }

    openMessages() {
        this.action.doAction("family_ai.action_family_ai_messages");
    }
}

registry.category("family_home_widgets").add("family_ai_push", FamilyPushCard, { sequence: 10 });
