const { launch, SYSTEM_CHROME } = require('./launch');

(async () => {
  const url = process.argv[2] || 'https://www.upwork.com/nx/find-work/best-matches';
  const { context, page, browser } = await launch({
    headless: false,
    executablePath: SYSTEM_CHROME,
  });

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });

    await page.waitForFunction(
      () => document.title.toLowerCase().includes('just a moment') === false,
      { timeout: 25000 }
    ).catch(() => {});
    await page.waitForTimeout(3000);

    const urlNow = page.url();
    const loggedIn = !urlNow.includes('/nx/login') && !urlNow.includes('verify');
    const title = await page.title();

    const jobs = await page.evaluate(() => {
      const texts = [...document.querySelectorAll('[data-test="JobTile"], [data-test="job-tile"], section article, [class*="job-tile"], [class*="JobTile"]')]
        .slice(0, 25)
        .map((el) => el.innerText.trim().split('\n').slice(0, 8).join(' | '))
        .filter(Boolean);
      return texts;
    });

    console.log(JSON.stringify({
      url: urlNow,
      title,
      loggedIn,
      cookieCount: (await context.cookies()).length,
      jobsFound: jobs.length,
      jobs: jobs.slice(0, 10),
    }, null, 2));

    await page.screenshot({ path: 'best-matches.png', fullPage: false });
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error('ERR', e.message);
  process.exit(1);
});