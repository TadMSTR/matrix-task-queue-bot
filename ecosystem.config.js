// PM2 ecosystem — matrix-task-queue-bot.
//
// WHY THIS FILE EXISTS. The bot previously had no start definition in version
// control: it existed only in PM2's own dump file, which is untracked and is
// regenerated from running state by every `pm2 save` rather than from reviewed
// configuration. Declaring it here makes `pm2 start ecosystem.config.js` the
// recovery path instead of `pm2 resurrect`. It also unblocks ordinary
// maintenance — removing an env var from a PM2 app requires `pm2 delete` +
// `pm2 start`, because `restart --update-env` can add or overwrite a value but
// never delete one.
//
// NO env BLOCK, DELIBERATELY. src/bot.py calls load_dotenv() on ENV_FILE,
// defaulting to ~/.secrets/matrix-task-queue-bot.env, and every setting the bot
// reads comes from there. This file therefore declares no environment at all,
// which is the correct amount: injecting a shared secrets bundle into a process
// that already loads its own would put credentials into the environment that
// nothing reads, and PM2 would write every one of them into its dump file at
// the next save.
//
// EXPECT A LARGE, MISLEADING ENV DIFF against the dump — roughly 90 variables.
// That is inherited login-shell state (SSH_*, XDG_*, DISPLAY from X11
// forwarding, and whatever the login profile sources), frozen in because the
// process was originally started by hand from an interactive session. It is not
// lost configuration and must not be copied back in.
//
// Note that `load_dotenv` does not override variables already present in the
// environment. Starting from this file rather than from an interactive shell
// means the bot's own env file is authoritative, which is the intended
// behaviour; it was verified before the cutover that no value the bot reads
// differs between the two sources.
//
// Corollary: systemd's `pm2 resurrect` runs in a NON-LOGIN context and does not
// re-source the login profile, which is why those inherited values get frozen
// into the dump to survive a boot. A process that loads its own secrets from an
// absolute path behaves identically under resurrect, under `pm2 start`, and
// from cron.
"use strict";

const path = require("path");

module.exports = {
  apps: [
    {
      name: "matrix-task-queue-bot",
      // The repo's own venv interpreter, resolved relative to this file rather
      // than hardcoded, so a clone at a different path still works.
      script: path.join(__dirname, "venv", "bin", "python"),
      args: ["-m", "src.bot"],
      // "none" because `script` is already a Python interpreter — letting PM2
      // pick would have it try to run the interpreter under node.
      interpreter: "none",
      // Load-bearing here, unlike most PM2 apps: `-m src.bot` is a module
      // reference resolved against the working directory.
      cwd: __dirname,
      exec_mode: "fork",
      autorestart: true,
      merge_logs: true,
    },
  ],
};
