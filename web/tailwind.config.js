/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                background: 'hsl(var(--background))',
                foreground: 'hsl(var(--foreground))',
                primary: {
                    DEFAULT: 'hsl(var(--primary))',
                    foreground: 'hsl(var(--primary-foreground))'
                },
                sidebar: {
                    DEFAULT: 'hsl(var(--sidebar-background))',
                    foreground: 'hsl(var(--sidebar-foreground))',
                    border: 'hsl(var(--sidebar-border))',
                    accent: 'hsl(var(--sidebar-accent))',
                    'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
                },
                card: {
                    DEFAULT: 'hsl(var(--card))',
                    foreground: 'hsl(var(--card-foreground))'
                },
                status: {
                    online: '#22c55e',
                    warning: '#f59e0b',
                    error: '#ef4444',
                    idle: '#606070',
                },
                harvest: '#6366f1',
                sync: '#8b5cf6',
                ingest: '#ec4899',
                index: '#22c55e',
            },
            borderRadius: {
                lg: 'var(--radius)',
                md: 'calc(var(--radius) - 2px)',
                sm: 'calc(var(--radius) - 4px)'
            },
            boxShadow: {
                'glow-harvest': '0 0 20px rgba(99, 102, 241, 0.2)',
                'glow-sync': '0 0 20px rgba(139, 92, 246, 0.2)',
                'glow-ingest': '0 0 20px rgba(236, 72, 153, 0.2)',
                'glow-index': '0 0 20px rgba(34, 197, 94, 0.2)',
            },
            animation: {
                'pulse-online': 'pulse-online 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            },
            keyframes: {
                'pulse-online': {
                    '0%, 100%': { opacity: 1 },
                    '50%': { opacity: .5 },
                }
            }
        },
    },
    plugins: [],
}
