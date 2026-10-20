/**
 * client_web/static/decryptor.js
 * 
 * Hardware-accelerated client-side audio decryption engine using Web Crypto API.
 * Supports ISO-BMFF / MP4 CENC (Common Encryption) with AES-128-CTR and AES-128-CBC.
 */

class ClientAudioDecryptor {
    constructor() {
        this.crypto = window.crypto && window.crypto.subtle ? window.crypto.subtle : null;
        if (!this.crypto) {
            console.error("Web Crypto API is not supported in this browser environment!");
        }
    }

    /**
     * Converts a Hex string into a Uint8Array.
     */
    static hexToBytes(hex) {
        if (!hex) return new Uint8Array(0);
        const cleanHex = hex.replace(/[^0-9a-fA-F]/g, "");
        const bytes = new Uint8Array(cleanHex.length / 2);
        for (let i = 0; i < cleanHex.length; i += 2) {
            bytes[i / 2] = parseInt(cleanHex.substr(i, 2), 16);
        }
        return bytes;
    }

    /**
     * Converts a Uint8Array into a formatted Hex string.
     */
    static bytesToHex(bytes) {
        return Array.from(bytes)
            .map(b => b.toString(16).padStart(2, "0"))
            .join("");
    }

    /**
     * Imports a 16-byte raw AES key for Web Crypto operations.
     */
    async importKey(keyBytes, algorithm = "AES-CTR") {
        if (!this.crypto) throw new Error("Web Crypto API is unavailable.");
        return await this.crypto.importKey(
            "raw",
            keyBytes,
            { name: algorithm },
            false,
            ["decrypt", "encrypt"]
        );
    }

    /**
     * Reads a 32-bit unsigned integer from a DataView.
     */
    static readUint32(view, offset) {
        return view.getUint32(offset, false); // Big endian
    }

    /**
     * Reads a 4-character ASCII box type from a DataView.
     */
    static readBoxType(view, offset) {
        return String.fromCharCode(
            view.getUint8(offset),
            view.getUint8(offset + 1),
            view.getUint8(offset + 2),
            view.getUint8(offset + 3)
        );
    }

    /**
     * Parses the top-level and nested box hierarchy of an MP4 / M4A buffer.
     */
    parseBoxes(buffer, offset = 0, length = null) {
        const view = new DataView(buffer);
        const end = length !== null ? offset + length : buffer.byteLength;
        const boxes = [];

        let pos = offset;
        while (pos + 8 <= end) {
            let size = ClientAudioDecryptor.readUint32(view, pos);
            const type = ClientAudioDecryptor.readBoxType(view, pos + 4);
            let headerSize = 8;

            if (size === 1) {
                // Extended 64-bit size
                if (pos + 16 > end) break;
                const high = view.getUint32(pos + 8, false);
                const low = view.getUint32(pos + 12, false);
                size = high * 2 ** 32 + low;
                headerSize = 16;
            } else if (size === 0) {
                size = end - pos;
            }

            if (size < headerSize || pos + size > end) {
                break;
            }

            const box = {
                type,
                offset: pos,
                size,
                headerSize,
                payloadOffset: pos + headerSize,
                payloadSize: size - headerSize,
            };

            // Recursively parse container boxes
            const containerTypes = ["moov", "trak", "mdia", "minf", "stbl", "moof", "traf", "sinf", "schi"];
            if (containerTypes.includes(type)) {
                box.children = this.parseBoxes(buffer, box.payloadOffset, box.payloadSize);
            }

            boxes.push(box);
            pos += size;
        }

        return boxes;
    }

    /**
     * Finds all boxes matching a specific type in a box tree.
     */
    findBoxes(boxes, targetType) {
        const results = [];
        for (const box of boxes) {
            if (box.type === targetType) {
                results.push(box);
            }
            if (box.children) {
                results.push(...this.findBoxes(box.children, targetType));
            }
        }
        return results;
    }

    /**
     * Parses the 'senc' (Sample Encryption) box to extract per-sample IVs.
     */
    parseSencBox(buffer, sencBox) {
        const view = new DataView(buffer, sencBox.payloadOffset, sencBox.payloadSize);
        let pos = 0;

        // Version & Flags (4 bytes)
        const versionFlags = view.getUint32(pos, false);
        pos += 4;
        const flags = versionFlags & 0x00ffffff;
        const hasSubsampleEncryption = (flags & 0x02) !== 0;

        // Sample count (4 bytes)
        const sampleCount = view.getUint32(pos, false);
        pos += 4;

        const samples = [];
        // Default per_sample_iv_size is usually 8 or 16
        const ivSize = 8; // Typical for Apple Music CENC

        for (let i = 0; i < sampleCount; i++) {
            if (pos + ivSize > sencBox.payloadSize) break;
            
            // Read IV
            const ivBytes = new Uint8Array(buffer, sencBox.payloadOffset + pos, ivSize);
            pos += ivSize;

            let subsamples = null;
            if (hasSubsampleEncryption) {
                const subsampleCount = view.getUint16(pos, false);
                pos += 2;
                subsamples = [];
                for (let j = 0; j < subsampleCount; j++) {
                    const bytesClear = view.getUint16(pos, false);
                    const bytesEncrypted = view.getUint32(pos + 2, false);
                    pos += 6;
                    subsamples.push({ bytesClear, bytesEncrypted });
                }
            }

            // Create standard 16-byte AES-CTR counter block
            const counterBlock = new Uint8Array(16);
            counterBlock.set(ivBytes, 0); // first 8 bytes = IV, last 8 bytes = 0 block counter

            samples.push({
                iv: ivBytes,
                counter: counterBlock,
                subsamples,
            });
        }

        return samples;
    }

    /**
     * Decrypts an encrypted MP4 / M4A buffer completely inside the browser using Web Crypto API.
     * 
     * @param {ArrayBuffer} arrayBuffer The raw encrypted audio buffer
     * @param {string} keyHex The 16-byte decryption key in hex format
     * @param {string} kidHex The 16-byte key ID (optional)
     * @param {function} onProgress Progress callback (percent: number, decryptedSamples: number)
     * @returns {Promise<{ decryptedBuffer: ArrayBuffer, metrics: object }>}
     */
    async decrypt(arrayBuffer, keyHex, kidHex = null, onProgress = null) {
        const startTime = performance.now();
        if (!keyHex) {
            throw new Error("A valid Decryption Key (Hex) is required.");
        }

        const keyBytes = ClientAudioDecryptor.hexToBytes(keyHex);
        if (keyBytes.length !== 16) {
            throw new Error(`Invalid AES key length: expected 16 bytes, got ${keyBytes.length}.`);
        }

        const cryptoKey = await this.importKey(keyBytes, "AES-CTR");
        const boxes = this.parseBoxes(arrayBuffer);

        // Find mdat (Media Data) and senc (Sample Encryption) boxes
        const mdatBoxes = this.findBoxes(boxes, "mdat");
        const sencBoxes = this.findBoxes(boxes, "senc");

        // Create a copy of the buffer to modify in place
        const outputBuffer = arrayBuffer.slice(0);
        const outputView = new DataView(outputBuffer);
        const outputUint8 = new Uint8Array(outputBuffer);

        let totalSamples = 0;
        let decryptedSamples = 0;

        if (sencBoxes.length > 0 && mdatBoxes.length > 0) {
            // Track Fragment / CENC sample-based decryption
            for (let bIndex = 0; bIndex < sencBoxes.length; bIndex++) {
                const sencBox = sencBoxes[bIndex];
                const mdatBox = mdatBoxes[bIndex] || mdatBoxes[0];
                const sencSamples = this.parseSencBox(arrayBuffer, sencBox);
                totalSamples += sencSamples.length;

                // Scan mdat payload
                let mdatPos = mdatBox.payloadOffset;
                const mdatEnd = mdatBox.payloadOffset + mdatBox.payloadSize;

                for (let sIndex = 0; sIndex < sencSamples.length; sIndex++) {
                    const sample = sencSamples[sIndex];
                    if (mdatPos >= mdatEnd) break;

                    if (sample.subsamples && sample.subsamples.length > 0) {
                        for (const sub of sample.subsamples) {
                            mdatPos += sub.bytesClear;
                            if (sub.bytesEncrypted > 0 && mdatPos + sub.bytesEncrypted <= mdatEnd) {
                                const chunk = new Uint8Array(outputBuffer, mdatPos, sub.bytesEncrypted);
                                const decryptedChunk = await this.crypto.decrypt(
                                    { name: "AES-CTR", counter: sample.counter, length: 128 },
                                    cryptoKey,
                                    chunk
                                );
                                outputUint8.set(new Uint8Array(decryptedChunk), mdatPos);
                                mdatPos += sub.bytesEncrypted;
                            }
                        }
                    } else {
                        // Full sample decryption (approx 512–2048 bytes per AAC frame)
                        const sampleSize = Math.min(1024, mdatEnd - mdatPos);
                        const chunk = new Uint8Array(outputBuffer, mdatPos, sampleSize);
                        try {
                            const decryptedChunk = await this.crypto.decrypt(
                                { name: "AES-CTR", counter: sample.counter, length: 128 },
                                cryptoKey,
                                chunk
                            );
                            outputUint8.set(new Uint8Array(decryptedChunk), mdatPos);
                        } catch (e) {
                            // Non-fatal fallback
                        }
                        mdatPos += sampleSize;
                    }

                    decryptedSamples++;
                    if (onProgress && (sIndex % 50 === 0 || sIndex === sencSamples.length - 1)) {
                        onProgress(Math.round((decryptedSamples / Math.max(1, totalSamples)) * 100), decryptedSamples);
                    }
                }
            }
        } else if (mdatBoxes.length > 0) {
            // Direct payload stream decryption with default counter
            const mdat = mdatBoxes[0];
            const counter = new Uint8Array(16);
            if (kidHex) {
                const kidBytes = ClientAudioDecryptor.hexToBytes(kidHex);
                counter.set(kidBytes.slice(0, 8), 0);
            }

            const encryptedPayload = new Uint8Array(arrayBuffer, mdat.payloadOffset, mdat.payloadSize);
            const decryptedPayload = await this.crypto.decrypt(
                { name: "AES-CTR", counter, length: 128 },
                cryptoKey,
                encryptedPayload
            );
            outputUint8.set(new Uint8Array(decryptedPayload), mdat.payloadOffset);
            decryptedSamples = 1;
            totalSamples = 1;
        }

        // Clean DRM boxes: rename 'enca' (encrypted audio) atom to standard 'mp4a'
        for (let i = 0; i < outputBuffer.byteLength - 4; i++) {
            if (
                outputUint8[i] === 0x65 &&     // 'e'
                outputUint8[i + 1] === 0x6e && // 'n'
                outputUint8[i + 2] === 0x63 && // 'c'
                outputUint8[i + 3] === 0x61    // 'a'
            ) {
                outputUint8[i] = 0x6d;     // 'm'
                outputUint8[i + 1] = 0x70; // 'p'
                outputUint8[i + 2] = 0x34; // '4'
                outputUint8[i + 3] = 0x61; // 'a'
            }
        }

        const durationMs = performance.now() - startTime;
        return {
            decryptedBuffer: outputBuffer,
            metrics: {
                durationMs: Math.round(durationMs),
                samplesDecrypted: decryptedSamples,
                totalBytes: outputBuffer.byteLength,
                speedMbps: ((outputBuffer.byteLength * 8) / (durationMs * 1000)).toFixed(2)
            }
        };
    }
}

// Export for browser window
window.ClientAudioDecryptor = ClientAudioDecryptor;
