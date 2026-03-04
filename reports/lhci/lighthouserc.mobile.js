module.exports = {
  ci: {
    collect: {
      url: ["http://localhost:3007"],
      numberOfRuns: 2,
      startServerCommand: "npm run start",
      startServerReadyPattern: "Ready in",
      startServerReadyTimeout: 120000,
      chromePath: "/root/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome",
      settings: {
        emulatedFormFactor: "mobile",
        chromeFlags: "--headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu",
      },
    },
    assert: {
      assertions: {
        "categories:performance": ["error", { minScore: 0.9 }],
        "categories:accessibility": ["error", { minScore: 0.9 }],
        "categories:best-practices": ["error", { minScore: 0.9 }],
        "categories:seo": ["error", { minScore: 0.9 }],
      },
    },
    upload: {
      target: "filesystem",
      outputDir: "../reports/lhci/mobile",
      reportFilenamePattern: "%%DATETIME%%-%%PATHNAME%%-mobile-%%RUN_INDEX%%.html",
    },
  },
};
