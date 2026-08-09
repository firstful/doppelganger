const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const PROFILE_DIR = path.join(__dirname, 'profiles', 'default');

const SYSTEM_CHROME = '/usr/bin/chromium';

const STEALTH_ARGS = [
  '--disable-blink-features=AutomationControlled',
  '--disable-infobars',
  '--disable-notifications',
  '--no-default-browser-check',
  '--no-first-run',
  '--disable-extensions',
  '--disable-component-update',
  '--disable-background-networking',
  '--disable-dev-shm-usage',
  '--mute-audio',
  '--metrics-recording-only',
];

async function launch(opts = {}) {
  fs.mkdirSync(PROFILE_DIR, { recursive: true });

  const useStealth = opts.stealth !== false;

  const launchOpts = {
    headless: opts.headless ?? false,
    args: useStealth ? STEALTH_ARGS : [],
    viewport: opts.viewport ?? { width: 1366, height: 768 },
    locale: opts.locale ?? 'en-US',
    timezoneId: opts.timezoneId ?? 'America/New_York',
    permissions: opts.permissions ?? [],
    channel: opts.channel,
    executablePath: opts.executablePath,
  };
  if (useStealth) launchOpts.ignoreDefaultArgs = ['--enable-automation'];
  if (opts.userAgent) launchOpts.userAgent = opts.userAgent;
  if (opts.geolocation) launchOpts.geolocation = opts.geolocation;

  const context = await chromium.launchPersistentContext(PROFILE_DIR, launchOpts);

  const page = opts.page || context.pages()[0] || (await context.newPage());

  if (useStealth) {
    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
      Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });

      const origQuery = window.navigator.permissions.query;
      window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : origQuery(parameters);

      window.chrome = window.chrome || {
        runtime: {}, loadTimes: () => ({}), csi: () => ({}),
      };
    });
  }

  return { context, page, browser: context.browser() };
}

module.exports = { launch, PROFILE_DIR, SYSTEM_CHROME, STEALTH_ARGS };