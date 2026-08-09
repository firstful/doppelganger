const { launch } = require('./launch');

(async () => {
  const { context, page, browser } = await launch();

  try {
    await page.goto('https://example.com', { waitUntil: 'domcontentloaded' });
    const checks = await page.evaluate(() => ({
      webdriver: navigator.webdriver,
      userAgent: navigator.userAgent,
      title: document.title,
    }));
    console.log('Stealth checks:', checks);

    await page.screenshot({ path: 'screenshot.png' });
    console.log('Saved screenshot.png');
  } finally {
    await browser.close();
  }

  console.log('Profile persisted on disk; cookies/localStorage saved.');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});