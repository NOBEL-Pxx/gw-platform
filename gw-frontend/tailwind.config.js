/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Aurora Maximalism: Deep Space Palette
        'space': {
          'dark': '#0A0A1A',       // Deep space void
          'navy': '#0A0F24',       // Midnight navy
          'nebula': '#1A0A2E',     // Nebula purple
          'stellar': '#0A1A2E',    // Stellar blue
        },
        'aurora': {
          'cyan': '#00F0FF',       // Aurora cyan
          'magenta': '#FF006E',    // Nebula magenta
          'violet': '#7C3AED',     // Cosmic violet
          'blue': '#3B82F6',       // Stellar blue
          'amber': '#FFB800',      // Solar amber
        },
        'glass': {
          'white': 'rgba(255,255,255,0.03)',
          'border': 'rgba(255,255,255,0.06)',
          'hover': 'rgba(255,255,255,0.06)',
        }
      },
      backgroundImage: {
        'nebula': 'linear-gradient(135deg, #1A0A2E 0%, #0A1A2E 50%, #0A0A1A 100%)',
        'nebula-reverse': 'linear-gradient(225deg, #1A0A2E 0%, #0A1A2E 50%, #0A0A1A 100%)',
        'aurora-glow': 'radial-gradient(ellipse at center, rgba(0,240,255,0.08) 0%, transparent 70%)',
      },
      boxShadow: {
        'aurora': '0 0 30px rgba(0,240,255,0.08), 0 0 60px rgba(124,58,237,0.04)',
        'glass': '0 8px 32px rgba(0,0,0,0.3)',
        'nebula': '0 0 40px rgba(255,0,110,0.06), 0 0 80px rgba(0,240,255,0.04)',
      },
      backdropBlur: {
        'xs': '2px',
      },
      animation: {
        'nebula-pulse': 'nebulaPulse 8s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
        'glow': 'glow 3s ease-in-out infinite',
        'fade-in': 'fadeIn 0.5s ease-out',
        'slide-up': 'slideUp 0.5s ease-out',
      },
      keyframes: {
        nebulaPulse: {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        glow: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(0,240,255,0.04)' },
          '50%': { boxShadow: '0 0 40px rgba(0,240,255,0.12)' },
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      }
    },
  },
  plugins: [],
};
