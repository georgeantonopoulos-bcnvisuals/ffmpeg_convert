const API = {
    async getSettings() {
        const res = await fetch('/api/settings');
        return await res.json();
    },

    async saveSettings(settings) {
        return await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
    },

    async browse(path = "") {
        const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        return await res.json();
    },

    async scan(path) {
        const res = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        return await res.json();
    },

    async startConversion(config) {
        const res = await fetch('/api/convert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        return await res.json();
    },

    async cancelConversion() {
        const res = await fetch('/api/cancel', { method: 'POST' });
        return await res.json();
    }
};
