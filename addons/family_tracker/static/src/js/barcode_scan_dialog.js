/** @odoo-module **/
/* global BarcodeDetector */

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { loadJS } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { buildZXingBarcodeDetector, isVideoElementReady } from "@web/webclient/barcode/ZXingBarcodeDetector";

const BEEP_URL = "/family_tracker/static/src/sounds/Scan.mp3";

// "Point the camera at a barcode" as a dialog that hands the code back through `onScan` and
// closes - for screens that only need to *look a product up* (the Meals diary's "From Groceries"),
// not change stock like the Scan Barcode screen. Camera handling follows that screen
// (groceries_barcode_scanner.js): the <video> only decodes, what you see is painted onto a
// <canvas>, because WebKit never paints the video itself inside Odoo's page.
export class BarcodeScanDialog extends Component {
    static template = "family_tracker.BarcodeScanDialog";
    static components = { Dialog };
    static props = {
        onScan: Function,
        title: { type: String, optional: true },
        close: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.videoRef = useRef("video");
        this.canvasRef = useRef("canvas");
        this.state = useState({
            cameraActive: false,
            starting: false,
            torchSupported: false,
            torchOn: false,
            manualBarcode: "",
        });
        this.isCameraSupported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        this.stream = null;
        this.track = null;
        this.pollTimer = null;
        this.drawRaf = null;
        this.finished = false;
        this.beep = new Audio(BEEP_URL);

        onWillStart(async () => {
            if ("BarcodeDetector" in window) {
                this.DetectorClass = BarcodeDetector;
            } else {
                await loadJS("/web/static/lib/zxing-library/zxing-library.js");
                this.DetectorClass = buildZXingBarcodeDetector(window.ZXing);
            }
        });
        // The dialog opens from a tap on the scan button, so the camera can start right away.
        onMounted(() => {
            if (this.isCameraSupported) {
                this.startCamera();
            }
        });
        onWillUnmount(() => this.stopCamera());
    }

    get title() {
        return this.props.title || _t("Scan barcode");
    }

    async startCamera() {
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
        clearInterval(this.pollTimer);
        this.pollTimer = null;
        if (this.drawRaf) {
            cancelAnimationFrame(this.drawRaf);
            this.drawRaf = null;
        }
        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
        this.track = null;
        this.state.torchOn = false;
        this.state.torchSupported = false;
        this.state.cameraActive = false;
    }

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

    async detectFrame() {
        const video = this.videoRef.el;
        if (this.finished || !video || !isVideoElementReady(video)) {
            return;
        }
        try {
            const codes = await this.detector.detect(video);
            if (codes.length) {
                this.done(codes[0].rawValue, true);
            }
        } catch (error) {
            // A frame without a readable code is normal (blur, nothing in view).
        }
    }

    onManualSubmit(ev) {
        ev.preventDefault();
        const barcode = this.state.manualBarcode.trim();
        if (barcode) {
            this.done(barcode, false);
        }
    }

    // One code is all the caller wants: hand it over and close.
    done(barcode, fromCamera) {
        if (this.finished) {
            return;
        }
        this.finished = true;
        if (fromCamera) {
            this.beep.play().catch(() => {});
            if ("vibrate" in window.navigator) {
                window.navigator.vibrate(100);
            }
        }
        this.stopCamera();
        this.props.onScan(barcode);
        this.props.close();
    }
}
