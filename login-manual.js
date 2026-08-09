const { launch, PROFILE_DIR, SYSTEM_CHROME } = require('./launch');

(async () => {
  const target = process.argv[2] || 'https://www.upwork.com';
  const { context, browser } = await launch({
    headless: false,
    executablePath: SYSTEM_CHROME,
    stealth: false,
  });

  const page = context.pages()[0] || (await context.newPage());
  await page.goto(target, { waitUntil: 'domcontentloaded' });

  console.log(`Opened plain Chromium at ${target}`);
  console.log('Manual login mode (no JS tampering, no automation cap removal).');
  console.log('Closing the window saves cookies to:');
  console.log(PROFILE_DIR);

  browser.on('disconnected', () => {
    console.log('Browser closed. Profile saved.');
    process.exit(0);
  });
})().catch((e) => {
  console.error(e);
  process.exit(1);
});