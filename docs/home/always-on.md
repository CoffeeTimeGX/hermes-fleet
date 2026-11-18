# Keep it running

## What needs your PC, and what does not

The VPSs do the work, and they **do not need your PC** to do it. A VPS keeps working
through its queue when your PC is off, asleep or offline, and it keeps every finished
job until your PC has downloaded it.

Your PC is needed for:

- talking to Hermes (terminal or Telegram),
- queuing new jobs,
- the scheduled checks: health alerts every 10 minutes, pulls every 30 minutes and the
  daily report.

So you can queue a day of work in the morning and turn the PC off. When it is back on,
the next scheduled pull collects everything that finished, and the health check tells
you about anything that went wrong.

If you want alerts and Telegram replies at any hour, keep the PC awake and logged in.

## Windows

- **No sleep on mains power.** *Settings > System > Power & battery > Screen and sleep*:
  set *When plugged in, put my device to sleep after* to **Never**. The screen can still
  turn off.
- **Laptops:** in *Control Panel > Power Options > Choose what closing the lid does*, set
  *When I close the lid (Plugged in)* to **Do nothing**.
- **Stay logged in.** The Hermes gateway runs as a scheduled task that starts when you
  log in and stops when you log out. Lock the screen (++windows+l++) instead of signing
  out.
- **Windows Update restarts.** After an update restart, Hermes comes back when you log
  in again. Set your *active hours* in *Settings > Windows Update > Advanced options* so
  restarts happen when they disturb least.
- **Tailscale** runs as a Windows service and starts with Windows. Nothing to do.

Check after a restart: `hermes gateway status`.

## Linux

- Turn off automatic suspend in your desktop's power settings, or for good:

    ```bash
    sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
    ```

- If nobody stays logged in, let your user's background services run anyway:

    ```bash
    sudo loginctl enable-linger $USER
    ```

## macOS

- *System Settings > Energy* (desktop Macs) or *Battery > Options* (laptops): turn on
  **Prevent automatic sleeping when the display is off**. From a terminal, the same for
  when the Mac is on its charger: `sudo pmset -c sleep 0`.

## After the PC was off

Nothing to do. Within 30 minutes the scheduled pull downloads what finished, and within
10 minutes the health check reports open problems. To catch up at once, ask Hermes
*"collect the finished videos and tell me what happened while I was away"*, or run
`fleet pull` and `fleet health`.
