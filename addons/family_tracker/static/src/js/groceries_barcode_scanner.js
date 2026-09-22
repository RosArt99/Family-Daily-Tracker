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

class GroceriesBarcodeScanner extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.videoRef = useRef("video");
        this.canvasRef = useRef("canvas");
        this.detector = null;
        this.stream = null;
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
            manualBarcode: "",
            cameraActive: false,
            starting: false,
            scanning: false,
            history: [],
        });

        onWillStart(async () => {
            if ("BarcodeDetector" in window) {
                this.DetectorClass = BarcodeDetector;
            } else {
                await loadJS("/web/static/lib/zxing-library/zxing-library.js");
                this.DetectorClass = buildZXingBarcodeDetector(window.ZXing);
            }
        });

        onWillUnmount(() => this.stopCamera());
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
        try {
            const result = await this.rpc("/groceries/scan", {
                barcode,
                action: this.state.action,
            });
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
                return;
            }
            if ("vibrate" in window.navigator) {
                window.navigator.vibrate(100);
            }
            this.notification.add(
                `${result.product_name} → ${result.state}` +
                    (result.product_created ? " " + _t("(new product)") : ""),
                { type: "success" }
            );
            this.state.history.unshift({ ...result, barcode, time: new Date().toLocaleTimeString() });
        } finally {
            this.processing = false;
            this.lastCodeAt = Date.now();
            this.scanTimer = setTimeout(() => {
                this.state.scanning = false;
            }, 1200);
        }
    }
}

GroceriesBarcodeScanner.template = "family_tracker.GroceriesBarcodeScanner";

registry.category("actions").add("family_tracker.barcode_scanner", GroceriesBarcodeScanner);
