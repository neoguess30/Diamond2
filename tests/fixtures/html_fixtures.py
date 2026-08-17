from __future__ import annotations
from typing import Dict, Tuple

REAL_FRAGMENT_FIXTURES: Dict[str, Tuple[bytes, str, float]] = {
    "AVAILABLE_BUY_NOW": (
        b'''<!DOCTYPE html>
        <html lang="en">
        <head><meta charset="utf-8"><title>@falcon on Fragment</title></head>
        <body class="theme-light">
          <div class="tm-page-wrap">
            <main class="tm-main-content">
              <section class="tm-section tm-header-section" data-username="falcon">
                <div class="tm-section-header">
                  <h1 class="tm-section-header-title">@falcon</h1>
                  <div class="tm-section-header-status tm-status-available">Available</div>
                </div>
                <div class="tm-section-subscribe">
                  <div class="tm-section-header-value icon-before icon-ton tm-price">5,000 TON</div>
                  <div class="table-cell-desc">~$14,250 USD</div>
                  <div class="tm-section-buttons">
                    <a href="/username/falcon?query=buy" class="btn btn-primary tm-btn">Buy Now</a>
                  </div>
                </div>
                <div class="tm-table-wrap">
                  <table class="table tm-table">
                    <tr class="table-row">
                      <td class="table-cell-title">Status</td>
                      <td class="table-cell-value"><span class="tm-status-avail">For sale</span></td>
                    </tr>
                    <tr class="table-row">
                      <td class="table-cell-title">Price</td>
                      <td class="table-cell-value icon-before icon-ton">5,000 TON</td>
                    </tr>
                  </table>
                </div>
              </section>
            </main>
          </div>
        </body>
        </html>''',
        "AVAILABLE",
        90.0
    ),
    "AUCTION_ACTIVE": (
        b'''<!DOCTYPE html>
        <html lang="en">
        <head><meta charset="utf-8"><title>@crypto on Fragment</title></head>
        <body class="theme-light">
          <div class="tm-page-wrap">
            <main class="tm-main-content">
              <section class="tm-section tm-header-section" data-username="crypto">
                <div class="tm-section-header">
                  <h1 class="tm-section-header-title">@crypto</h1>
                  <div class="tm-section-header-status tm-status-auction">In auction</div>
                </div>
                <div class="tm-section-subscribe">
                  <div class="table-cell-desc">Current bid</div>
                  <div class="tm-section-header-value icon-before icon-ton tm-price">12,500 TON</div>
                  <div class="table-cell-desc">Ends in 2 days 14 hours</div>
                  <div class="tm-section-buttons">
                    <button class="btn btn-primary tm-btn">Place bid</button>
                  </div>
                </div>
                <div class="tm-table-wrap">
                  <table class="table tm-table">
                    <tr class="table-row">
                      <td class="table-cell-title">Minimum bid</td>
                      <td class="table-cell-value icon-before icon-ton">13,125 TON</td>
                    </tr>
                    <tr class="table-row">
                      <td class="table-cell-title">Step</td>
                      <td class="table-cell-value icon-before icon-ton">625 TON</td>
                    </tr>
                  </table>
                </div>
              </section>
            </main>
          </div>
        </body>
        </html>''',
        "AUCTION",
        90.0
    ),
    "SOLD_COMPLETED": (
        b'''<!DOCTYPE html>
        <html lang="en">
        <head><meta charset="utf-8"><title>@meta on Fragment</title></head>
        <body class="theme-light">
          <div class="tm-page-wrap">
            <main class="tm-main-content">
              <section class="tm-section tm-header-section" data-username="meta">
                <div class="tm-section-header">
                  <h1 class="tm-section-header-title">@meta</h1>
                  <div class="tm-section-header-status tm-status-sold">Sold</div>
                </div>
                <div class="tm-section-subscribe">
                  <div class="table-cell-desc">Sold for</div>
                  <div class="tm-section-header-value icon-before icon-ton tm-price">85,000 TON</div>
                  <div class="table-cell-desc">Sale completed on Dec 12, 2024</div>
                </div>
                <div class="tm-table-wrap">
                  <table class="table tm-table">
                    <tr class="table-row">
                      <td class="table-cell-title">Winning bid</td>
                      <td class="table-cell-value icon-before icon-ton">85,000 TON</td>
                    </tr>
                    <tr class="table-row">
                      <td class="table-cell-title">Owner</td>
                      <td class="table-cell-value">EQB0...3f9a</td>
                    </tr>
                  </table>
                </div>
              </section>
            </main>
          </div>
        </body>
        </html>''',
        "SOLD",
        90.0
    ),
    "UNAVAILABLE_TAKEN": (
        b'''<!DOCTYPE html>
        <html lang="en">
        <head><meta charset="utf-8"><title>@durov on Fragment</title></head>
        <body class="theme-light">
          <div class="tm-page-wrap">
            <main class="tm-main-content">
              <section class="tm-section tm-header-section" data-username="durov">
                <div class="tm-section-header">
                  <h1 class="tm-section-header-title">@durov</h1>
                  <div class="tm-section-header-status tm-status-unavail">Unavailable</div>
                </div>
                <div class="tm-section-subscribe">
                  <div class="tm-section-header-status-desc">This username is already taken on Telegram and not for sale on Fragment.</div>
                </div>
                <div class="tm-table-wrap">
                  <table class="table tm-table">
                    <tr class="table-row">
                      <td class="table-cell-title">Telegram Handle</td>
                      <td class="table-cell-value">Assigned to user</td>
                    </tr>
                  </table>
                </div>
              </section>
            </main>
          </div>
        </body>
        </html>''',
        "UNAVAILABLE",
        90.0
    ),
    "CLOUDFLARE_CHALLENGE": (
        b'''<!DOCTYPE html>
        <html>
        <head><title>Just a moment...</title></head>
        <body>
          <div class="cf-challenge-wrap">
            <h2>Checking your browser before accessing fragment.com</h2>
            <div id="cf-challenge-running"></div>
          </div>
        </body>
        </html>''',
        "ERROR",
        0.0
    ),
    "AMBIGUOUS_NO_EVIDENCE": (
        b'''<!DOCTYPE html>
        <html>
        <head><title>Random Service Page</title></head>
        <body>
          <div class="content-wrapper">
            <p>Welcome to our general service catalog. We offer enterprise consulting and cloud infrastructure.</p>
          </div>
        </body>
        </html>''',
        "UNKNOWN",
        0.0
    )
}