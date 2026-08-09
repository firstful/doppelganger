const { launch, SYSTEM_CHROME } = require('./launch');
(async () => {
  const { context, page, browser } = await launch({
    headless: false,
    executablePath: SYSTEM_CHROME,
  });
  const cookies = await context.cookies();
  console.log('total cookies:', cookies.length);
  const interesting = cookies.filter((c) =>
    /upwork|cloudflare|clearance|session|pusher|xsrf|csrf/i.test(c.name) || /upwork|cloudflare/i.test(c.domain)
  );
  for (const c of interesting.slice(0, 40)) {
    console.log(`${c.name} [${c.domain}] ${c.httpOnly ? 'httpOnly' : ''} exp=${new Date(c.expires*1000).toISOString()}`);
  }
  await browser.close();
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });