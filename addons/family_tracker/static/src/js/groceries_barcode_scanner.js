/** @odoo-module **/
/* global BarcodeDetector */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { buildZXingBarcodeDetector, isVideoElementReady } from "@web/webclient/barcode/ZXingBarcodeDetector";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, useRef, onWillStart, onWillUnmount } from "@odoo/owl";

// We deliberately don't reuse Odoo's own scanBarcode()/BarcodeDialog: that dialog
// renders its <video> inside a fullscreen Bootstrap modal relying on percentage
// height chains, which collapses to 0 height on iOS Safari (dynamic toolbar +
// 100vh quirks) - camera turns on but nothing is ever visible. Detection itself
// (native BarcodeDetector / ZXing fallback) works fine, so we reuse only that part
// and render our own plain, non-modal <video> with predictable CSS.
//
// The <video> element itself still refuses to *paint* when embedded in Odoo's own
// page (confirmed: getUserMedia/play()/readyState all succeed identically to a bare
// standalone page, only the pixels never show - a WebKit video-compositing quirk we
// couldn't pin down further without Safari devtools). Workaround: keep the <video>
// in the DOM (decoding, hidden) purely as the frame *source*, and paint what the
// user actually sees onto a <canvas> via drawImage() every frame instead - canvas
// bitmaps aren't subject to this bug.
const BEEP_URL = "/family_tracker/static/src/sounds/Scan.mp3";
const MAX_COUNT = 999;

// The four scan modes, shown as radio-style buttons. "find" doesn't touch stock at all: it only
// looks the barcode up and opens that product's card.
const MODES = [
    { value: "to_buy", label: _t("To Buy"), icon: "fa-shopping-cart" },
    { value: "in_stock", label: _t("In Stock"), icon: "fa-check-circle" },
    { value: "consumed", label: _t("Consumed"), icon: "fa-archive" },
    { value: "find", label: _t("Find Product"), icon: "fa-search" },
];

// What each action's running total is called and which of the scan's returned totals it reads.
const TOTAL_LABELS = {
    to_buy: "On Shopping List",
    in_stock: "Total In Stock",
    consumed: "Total Consumed",
};

class GroceriesBarcodeScanner extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.modes = MODES;
        this.videoRef = useRef("video");
        this.canvasRef = useRef("canvas");
        this.detector = null;
        this.stream = null;
        this.track = null;
        this.pollTimer = null;
        this.drawRaf = null;
        this.scanTimer = null;
        this.processing = false;
        this.lastCode = null;
        this.lastCodeAt = 0;
        this.beep = new Audio(BEEP_URL);
        this.beep.preload = "auto";
        this.isCameraSupported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

        this.state = useState({
            action: "in_stock",
            count: "1",
            manualBarcode: "",
            cameraActive: false,
            starting: false,
            scanning: false,
            torchSupported: false,
            torchOn: false,
            history: [],
            lastScan: null,
        });
        this.lastScanTimer = null;

        onWillStart(async () => {
            if ("BarcodeDetector" in window) {
                this.DetectorClass = BarcodeDetector;
            } else {
                await loadJS("/web/static/lib/zxing-library/zxing-library.js");
                this.DetectorClass = buildZXingBarcodeDetector(window.ZXing);
            }
        });

        onWillUnmount(() => {
            this.stopCamera();
            clearTimeout(this.lastScanTimer);
        });
    }

    // iOS only lets a page play audio later (from a timer/after an await) if
    // playback was already started once inside a real tap - do a silent play/pause now.
    unlockAudio() {
        this.beep.muted = true;
        this.beep
            .play()
            .then(() => {
                this.beep.pause();
                this.beep.currentTime = 0;
            })
            .catch(() => {})
            .finally(() => {
                this.beep.muted = false;
            });
    }

    // ---- how many identical packs this one scan stands for ----

    get countValue() {
        const n = parseInt(this.state.count, 10);
        return Number.isFinite(n) && n > 0 ? Math.min(n, MAX_COUNT) : 1;
    }

    onCountInput(ev) {
        // Digits only - a phone number pad has no way to type anything else anyway, but
        // paste/autofill could.
        this.state.count = ev.target.value.replace(/\D/g, "");
    }

    onCountBlur() {
        this.state.count = String(this.countValue);
    }

    stepCount(delta) {
        this.state.count = String(Math.min(MAX_COUNT, Math.max(1, this.countValue + delta)));
    }

    get isFindMode() {
        return this.state.action === "find";
    }

    setMode(value) {
        this.state.action = value;
    }

    // ---- flashlight (the camera's torch). Android Chrome exposes it; iPhone Safari does not
    // expose it to web pages at all, so there the button just stays disabled. ----

    async toggleTorch() {
        if (!this.track || !this.state.torchSupported) {
            return;
        }
        const next = !this.state.torchOn;
        try {
            await this.track.applyConstraints({ advanced: [{ torch: next }] });
            this.state.torchOn = next;
        } catch (error) {
            this.notification.add(_t("Could not switch the flashlight."), { type: "warning" });
        }
    }

    // On-screen confirmation of the scan just made (a card pinned under the top bar, so it's
    // visible however far down the page is scrolled while the camera is running).
    showScanResult(result) {
        clearTimeout(this.lastScanTimer);
        this.state.lastScan = result;
        this.lastScanTimer = setTimeout(() => {
            this.state.lastScan = null;
        }, 6000);
    }

    dismissScanResult() {
        clearTimeout(this.lastScanTimer);
        this.state.lastScan = null;
    }

    stateLabel(action) {
        const mode = MODES.find((m) => m.value === action);
        return mode ? mode.label : action;
    }

    totalLabel(action) {
        return TOTAL_LABELS[action] || "Total";
    }

    async onStartCamera() {
        this.unlockAudio();
        this.state.starting = true;
        try {
            const formats = await this.DetectorClass.getSupportedFormats();
            this.detector = new this.DetectorClass({ formats });
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "environment" },
                audio: false,
            });
            const video = this.videoRef.el;
            const canvas = this.canvasRef.el;
            video.onloadedmetadata = () => {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
            };
            this.track = this.stream.getVideoTracks()[0] || null;
            const capabilities = (this.track && this.track.getCapabilities && this.track.getCapabilities()) || {};
            this.state.torchSupported = !!capabilities.torch;
            video.srcObject = this.stream;
            await video.play();
            this.state.cameraActive = true;
            this.pollTimer = setInterval(() => this.detectFrame(), 200);
            const ctx = canvas.getContext("2d");
            const drawFrame = () => {
                if (!this.state.cameraActive) {
                    return;
                }
                if (video.videoWidth) {
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                }
                this.drawRaf = requestAnimationFrame(drawFrame);
            };
            drawFrame();
        } catch (error) {
            this.notification.add(_t("Could not start camera: ") + (error.message || error), {
                type: "danger",
            });
            this.stopCamera();
        } finally {
            this.state.starting = false;
        }
    }

    stopCamera() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
        if (this.drawRaf) {
            cancelAnimationFrame(this.drawRaf);
            this.drawRaf = null;
        }
        clearTimeout(this.scanTimer);
        this.state.scanning = false;
        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
        this.track = null;
        this.state.torchOn = false;
        this.state.torchSupported = false;
        this.state.cameraActive = false;
    }

    async detectFrame() {
        const video = this.videoRef.el;
        // A brand-new product can take several seconds (Open Food Facts lookup +
        // photo download); ignore frames meanwhile or the same pack gets scanned twice.
        if (this.processing || !video || !isVideoElementReady(video)) {
            return;
        }
        try {
            const codes = await this.detector.detect(video);
            if (codes.length) {
                const barcode = codes[0].rawValue;
                // Debounce: a held-up product would otherwise fire dozens of
                // identical scans per second at this poll rate.
                if (barcode === this.lastCode && Date.now() - this.lastCodeAt < 2000) {
                    return;
                }
                await this.processBarcode(barcode);
            }
        } catch (error) {
            // Per-frame decode misses are expected (blur, no code in view) - not worth surfacing.
        }
    }

    async onManualSubmit(ev) {
        ev.preventDefault();
        this.unlockAudio();
        const barcode = this.state.manualBarcode.trim();
        if (!barcode) {
            return;
        }
        this.state.manualBarcode = "";
        await this.processBarcode(barcode);
    }

    async processBarcode(barcode) {
        this.processing = true;
        this.lastCode = barcode;
        this.state.scanning = true;
        clearTimeout(this.scanTimer);
        // Beep on the read itself, like a store scanner - not after the (slow) server round trip.
        this.beep.currentTime = 0;
        this.beep.play().catch(() => {});
        const count = this.countValue;
        try {
            if (this.isFindMode) {
                await this.findProduct(barcode);
                return;
            }
            const result = await this.rpc("/groceries/scan", {
                barcode,
                action: this.state.action,
                count,
            });
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
                return;
            }
            if ("vibrate" in window.navigator) {
                window.navigator.vibrate(100);
            }
            this.showScanResult({ ...result, barcode });
            this.state.history.unshift({ ...result, barcode, time: new Date().toLocaleTimeString() });
            // Reset to 1 so the next (probably different) product isn't scanned with a
            // leftover count by mistake.
            this.state.count = "1";
        } finally {
            this.processing = false;
            this.lastCodeAt = Date.now();
            this.scanTimer = setTimeout(() => {
                this.state.scanning = false;
            }, 1200);
        }
    }

    // "Find Product": no stock change, and no Open Food Facts lookup either - just open the
    // card of a product we already have.
    async findProduct(barcode) {
        const [product] = await this.orm.searchRead(
            "groceries.product", [["barcode", "=", barcode]], ["id"], { limit: 1 }
        );
        if (!product) {
            this.notification.add(_t("No product with barcode %s in your catalog yet.", barcode), {
                type: "warning",
            });
            return;
        }
        if ("vibrate" in window.navigator) {
            window.navigator.vibrate(100);
        }
        this.stopCamera();
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "groceries.product",
            res_id: product.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

GroceriesBarcodeScanner.template = "family_tracker.GroceriesBarcodeScanner";

registry.category("actions").add("family_tracker.barcode_scanner", GroceriesBarcodeScanner);
