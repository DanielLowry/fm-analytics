/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "../src/fm_analytics/web/templates/**/*.html",
    "../src/fm_analytics/web/**/*.py",
  ],
  darkMode: ["class", ".dark"],
  theme: { extend: {} },
  plugins: [require("@tailwindcss/forms")],
};
