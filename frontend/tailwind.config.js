/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 墨绿主色（对齐设计稿发送按钮 / Logo）
        brand: {
          50: "#EAF5F0",
          100: "#D2EADF",
          200: "#A6D5C0",
          300: "#6FBB9C",
          400: "#3D9F7C",
          500: "#12855F",
          600: "#0E7354",
          700: "#0B5D45",
          800: "#084A37",
          900: "#063827",
        },
        // 侧栏与页面底色（soft 用于表头/弹窗页脚等次级面）
        canvas: {
          DEFAULT: "#F7F7F5",
          soft: "#FAFAF9",
        },
        hairline: "#EDEDEA",
        // 用户消息气泡
        bubble: "#F1F1EE",
        // 文字墨阶：200~300 用于占位与分隔，600 用于次级正文
        ink: {
          900: "#1F2328",
          700: "#3D444D",
          600: "#4B5563",
          500: "#6B7280",
          400: "#8B9198",
          300: "#B4B9C0",
          200: "#D7DAE0",
        },
      },
      borderRadius: {
        // 控件统一 8px，卡片 10px，弹窗 14px
        control: "8px",
        card: "10px",
        panel: "14px",
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "PingFang SC",
          "Hiragino Sans GB",
          "Microsoft YaHei",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 24, 40, 0.04)",
        pop: "0 12px 32px rgba(16, 24, 40, 0.12)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.15" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.22s ease-out both",
        blink: "blink 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
