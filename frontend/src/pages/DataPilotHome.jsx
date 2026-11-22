// Imports
import React from 'react';
/**
 * DataPilot AI — public landing page.
 * This component intentionally contains its own CSS so the existing
 * spreadsheet/application styles are not changed.
 */
export default function DataPilotHome() {
    // Function: enter app
    const enterApp = () => {
        window.location.href = '/app';
    };
    return (<div className="dp-home">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

        .dp-home,
        .dp-home * { box-sizing: border-box; }

        .dp-home {
          min-height: 100vh;
          width: 100%;
          overflow: hidden;
          background: #050505;
          color: #fff;
          font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          position: relative;
        }

        .dp-home button { font: inherit; }

        .dp-home-shell {
          min-height: 100vh;
          display: grid;
          grid-template-columns: minmax(430px, 43%) minmax(0, 57%);
        }

        .dp-home-left {
          position: relative;
          z-index: 3;
          min-height: 100vh;
          padding: 38px 48px 42px;
          display: flex;
          flex-direction: column;
          background:
            radial-gradient(circle at 0% 20%, rgba(233,138,224,.055), transparent 35%),
            #090909;
          border-right: 1px solid rgba(255,255,255,.045);
        }

        .dp-brand {
          display: flex;
          align-items: center;
          gap: 12px;
          width: fit-content;
          animation: dp-rise .75s .05s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-brand-mark {
          width: 31px;
          height: 35px;
          filter: drop-shadow(0 0 16px rgba(233,138,224,.35));
          flex: 0 0 auto;
        }

        .dp-brand-name {
          font-size: 20px;
          line-height: 1;
          letter-spacing: -.045em;
          font-weight: 500;
          color: #f6f2f7;
        }

        .dp-brand-name span { font-weight: 300; color: #e98ae0; }

        .dp-language {
          margin-left: auto;
          border: 1px solid rgba(255,255,255,.09);
          background: rgba(255,255,255,.025);
          color: rgba(255,255,255,.66);
          border-radius: 999px;
          padding: 8px 13px;
          font-size: 11px;
          letter-spacing: .01em;
        }

        .dp-copy {
          max-width: 545px;
          margin: auto 0;
          padding: 82px 0 70px;
        }

        .dp-eyebrow {
          display: inline-flex;
          align-items: center;
          gap: 9px;
          color: #d9b9d6;
          font-size: 11px;
          letter-spacing: .16em;
          text-transform: uppercase;
          margin-bottom: 25px;
          animation: dp-rise .8s .18s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-eyebrow-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #e98ae0;
          box-shadow: 0 0 14px #e98ae0;
        }

        .dp-title {
          margin: 0;
          font-size: clamp(42px, 5vw, 70px);
          line-height: .98;
          letter-spacing: -.065em;
          font-weight: 500;
          color: #fff;
          animation: dp-rise .9s .28s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-title-gradient {
          display: block;
          background: linear-gradient(100deg, #f2a0e5 5%, #e98ae0 38%, #b9a9ff 95%);
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
        }

        .dp-description {
          margin: 26px 0 0;
          max-width: 500px;
          color: rgba(255,255,255,.52);
          font-size: 15px;
          line-height: 1.8;
          font-weight: 300;
          animation: dp-rise .9s .4s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-actions {
          display: flex;
          align-items: center;
          gap: 18px;
          margin-top: 34px;
          animation: dp-rise .9s .52s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-enter {
          appearance: none;
          border: 0;
          cursor: pointer;
          min-height: 48px;
          padding: 0 23px;
          border-radius: 999px;
          color: #160d17;
          font-weight: 600;
          font-size: 13px;
          background: linear-gradient(100deg, #f2a0e5, #e98ae0 48%, #c9b4ff);
          box-shadow: 0 0 0 1px rgba(255,255,255,.09) inset, 0 10px 38px rgba(233,138,224,.16);
          transition: transform .2s ease, box-shadow .2s ease, filter .2s ease;
        }

        .dp-enter:hover {
          transform: translateY(-2px);
          filter: brightness(1.06);
          box-shadow: 0 0 0 1px rgba(255,255,255,.16) inset, 0 14px 44px rgba(233,138,224,.25);
        }

        .dp-enter:active { transform: translateY(0); }

        .dp-secondary {
          color: rgba(255,255,255,.42);
          font-size: 12px;
          font-weight: 400;
        }

        .dp-bottom-note {
          display: flex;
          align-items: center;
          gap: 10px;
          color: rgba(255,255,255,.24);
          font-size: 10px;
          letter-spacing: .04em;
          animation: dp-rise .9s .68s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-bottom-note::before {
          content: '';
          width: 24px;
          height: 1px;
          background: rgba(233,138,224,.45);
        }

        .dp-home-right {
          position: relative;
          min-height: 100vh;
          overflow: hidden;
          isolation: isolate;
          background:
            radial-gradient(circle at 63% 46%, rgba(154,92,191,.19), transparent 29%),
            radial-gradient(circle at 55% 77%, rgba(233,73,201,.12), transparent 27%),
            linear-gradient(145deg, #050505 0%, #080609 43%, #170d20 100%);
        }

        .dp-home-right::before {
          content: '';
          position: absolute;
          inset: 0;
          background:
            linear-gradient(90deg, rgba(0,0,0,.18), transparent 30%),
            radial-gradient(circle at 50% 50%, transparent 0%, rgba(0,0,0,.18) 70%, rgba(0,0,0,.52) 100%);
          pointer-events: none;
          z-index: 1;
        }

        .dp-showcase-copy {
          position: absolute;
          top: 9.5%;
          left: 10%;
          right: 8%;
          z-index: 5;
          animation: dp-headline .95s .42s cubic-bezier(.2,.8,.2,1) both;
        }

        .dp-showcase-title {
          margin: 0;
          font-size: clamp(27px, 3vw, 40px);
          line-height: 1.06;
          letter-spacing: -.055em;
          font-weight: 500;
          max-width: 590px;
        }

        .dp-showcase-title .gradient {
          display: block;
          background: linear-gradient(100deg, #e98ae0 10%, #f0a5e5 48%, #c5b5ff 100%);
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
        }

        .dp-join {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          margin-top: 18px;
          color: rgba(255,255,255,.68);
          font-size: 11px;
          letter-spacing: .06em;
          text-decoration: none;
        }

        .dp-join-triangle {
          width: 0;
          height: 0;
          border-top: 5px solid transparent;
          border-bottom: 5px solid transparent;
          border-left: 8px solid #e98ae0;
          filter: drop-shadow(0 0 8px rgba(233,138,224,.65));
        }

        .dp-scene {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          z-index: 2;
          opacity: 0;
          animation: dp-scene-in 1.25s .35s ease-out forwards;
        }

        .dp-ghost-3d {
          fill: none;
          stroke: rgba(218,190,225,.055);
          stroke-width: 2;
          letter-spacing: -15px;
        }

        .dp-orbit-back {
          fill: none;
          stroke: rgba(241,138,224,.64);
          stroke-width: 1.35;
          filter: drop-shadow(0 0 7px rgba(233,138,224,.5));
        }

        .dp-orbit-front {
          fill: none;
          stroke: rgba(249,164,231,.88);
          stroke-width: 1.55;
          filter: drop-shadow(0 0 9px rgba(233,138,224,.7));
        }

        .dp-orbit-dot {
          fill: #f7b2eb;
          filter: drop-shadow(0 0 10px rgba(255,157,236,1));
        }

        .dp-floor {
          fill: url(#dpFloorGlow);
          opacity: .8;
        }

        .dp-robot {
          filter: drop-shadow(0 18px 28px rgba(0,0,0,.45)) drop-shadow(0 0 20px rgba(208,133,229,.13));
        }

        .dp-pedestal {
          fill: url(#dpPedestal);
          stroke: rgba(255,255,255,.13);
          stroke-width: .6;
        }

        .dp-pedestal-rim {
          fill: none;
          stroke: #db6fcb;
          stroke-width: 2;
          opacity: .88;
          filter: drop-shadow(0 0 8px rgba(233,138,224,.65));
        }

        .dp-chip {
          position: absolute;
          z-index: 4;
          border: 1px solid rgba(255,255,255,.07);
          background: rgba(12,8,14,.54);
          backdrop-filter: blur(15px);
          border-radius: 12px;
          padding: 10px 12px;
          min-width: 118px;
          box-shadow: 0 15px 45px rgba(0,0,0,.18);
          animation: dp-float 4.8s ease-in-out infinite;
        }

        .dp-chip.one { top: 43%; left: 8%; animation-delay: -.8s; }
        .dp-chip.two { top: 54%; right: 8%; animation-delay: -2.2s; }
        .dp-chip.three { bottom: 17%; left: 17%; animation-delay: -3.1s; }

        .dp-chip-label { color: rgba(255,255,255,.34); font-size: 8px; letter-spacing: .11em; text-transform: uppercase; }
        .dp-chip-value { margin-top: 5px; color: rgba(255,255,255,.83); font-size: 12px; font-weight: 500; }
        .dp-chip-value span { color: #e98ae0; }

        .dp-grid {
          position: absolute;
          z-index: 1;
          left: -10%;
          right: -10%;
          bottom: -15%;
          height: 46%;
          opacity: .09;
          transform: perspective(450px) rotateX(63deg);
          background-image: linear-gradient(rgba(233,138,224,.8) 1px, transparent 1px), linear-gradient(90deg, rgba(233,138,224,.8) 1px, transparent 1px);
          background-size: 46px 46px;
          mask-image: linear-gradient(to top, #000, transparent 85%);
        }

        @keyframes dp-rise {
          from { opacity: 0; transform: translateY(24px); }
          to { opacity: 1; transform: translateY(0); }
        }

        @keyframes dp-headline {
          from { opacity: 0; transform: translateY(20px); clip-path: inset(0 0 100% 0); }
          to { opacity: 1; transform: translateY(0); clip-path: inset(0 0 0 0); }
        }

        @keyframes dp-scene-in {
          from { opacity: 0; transform: translateY(18px) scale(.985); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }

        @keyframes dp-float {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-8px); }
        }

        @media (max-width: 900px) {
          .dp-home-shell { grid-template-columns: 1fr; }
          .dp-home-left { min-height: 100vh; border-right: 0; }
          .dp-home-right { display: none; }
          .dp-copy { max-width: 680px; }
          .dp-title { font-size: clamp(42px, 12vw, 68px); }
        }

        /* Mobile overflow safeguard */
        @media (max-width: 560px) {
          .dp-home { width:100%; min-width:0; overflow-x:hidden; }
          .dp-home-shell, .dp-home-left { width:100%; min-width:0; }
          .dp-brand { max-width:100%; }
          .dp-brand-name { font-size:18px; }
          .dp-language { padding:7px 10px; font-size:10px; }
          .dp-description { max-width:100%; }
        }

        @media (max-width: 560px) {
          .dp-home-left { padding: 27px 24px 31px; }
          .dp-copy { padding: 70px 0 55px; }
          .dp-title { font-size: 43px; }
          .dp-description { font-size: 14px; line-height: 1.75; }
          .dp-actions { align-items: flex-start; flex-direction: column; gap: 13px; }
          .dp-enter { width: 100%; }
        }

        @media (prefers-reduced-motion: reduce) {
          .dp-brand, .dp-eyebrow, .dp-title, .dp-description, .dp-actions, .dp-bottom-note,
          .dp-showcase-copy, .dp-scene, .dp-chip { animation: none !important; opacity: 1 !important; transform: none !important; clip-path: none !important; }
        }
      `}</style>

      <div className="dp-home-shell">
        <section className="dp-home-left" aria-label="DataPilot AI introduction">
          <header className="dp-brand">
            <svg className="dp-brand-mark" viewBox="0 0 34 38" aria-hidden="true">
              <defs>
                <linearGradient id="dpLogoGradient" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#f3a2e6"/>
                  <stop offset=".52" stopColor="#e98ae0"/>
                  <stop offset="1" stopColor="#aa9bff"/>
                </linearGradient>
              </defs>
              <path fill="url(#dpLogoGradient)" d="M17 1.5c1.2 6.2 8.9 7.6 11.3 14.5 2.9 8.3-2.8 16.4-11.3 19.5C8.4 32.4 3 26.7 3 19.7 3 12.6 9.1 9.4 13.6 5.2 15.2 3.7 16.2 2.5 17 1.5Z"/>
              <path fill="#090909" opacity=".92" d="M17.3 10.2c.5 4.3 5.1 5.9 5.1 10.1 0 4-2.6 6.7-5.7 7.9-3.4-1.5-5.2-4.1-5.2-7.2 0-3.2 2.7-5.4 4.5-7.2.7-.8 1.1-2 1.3-3.6Z"/>
            </svg>
            <div className="dp-brand-name">DataPilot<span> AI</span></div>
            <div className="dp-language">English⌄</div>
          </header>

          <div className="dp-copy">
            <div className="dp-eyebrow"><span className="dp-eyebrow-dot"/> AI-powered data intelligence</div>
            <h1 className="dp-title">
              Turn your data<br />
              <span className="dp-title-gradient">into decisions.</span>
            </h1>
            <p className="dp-description">
              Upload, clean, analyze and understand your business data with one intelligent workspace built for modern analysts.
            </p>

            <div className="dp-actions">
              <button type="button" className="dp-enter" onClick={enterApp}>
                Enter DataPilot AI&nbsp; →
              </button>
              <span className="dp-secondary">Your existing analytics workspace</span>
            </div>
          </div>

          <div className="dp-bottom-note">Business intelligence, spreadsheets &amp; AI analysis</div>
        </section>

        <section className="dp-home-right" aria-label="DataPilot AI showcase">
          <div className="dp-showcase-copy">
            <h2 className="dp-showcase-title">
              Your data. One intelligent
              <span className="gradient">command center.</span>
            </h2>
            <a className="dp-join" href="/app" onClick={(e) => { e.preventDefault(); enterApp(); }}>
              <span className="dp-join-triangle"/> Explore DataPilot AI
            </a>
          </div>

          <div className="dp-chip one"><div className="dp-chip-label">AI insight</div><div className="dp-chip-value">Revenue <span>+18.4%</span></div></div>
          <div className="dp-chip two"><div className="dp-chip-label">Data quality</div><div className="dp-chip-value">98.7% <span>ready</span></div></div>
          <div className="dp-chip three"><div className="dp-chip-label">Ask your data</div><div className="dp-chip-value">Natural language</div></div>

          <div className="dp-grid"/>

          <svg className="dp-scene" viewBox="0 0 421 1200" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
            <defs>
              <radialGradient id="dpFloorGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0" stopColor="#e98ae0" stopOpacity=".35"/>
                <stop offset="1" stopColor="#e98ae0" stopOpacity="0"/>
              </radialGradient>
              <linearGradient id="dpPedestal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#34303a"/>
                <stop offset=".18" stopColor="#17151a"/>
                <stop offset="1" stopColor="#050505"/>
              </linearGradient>
            </defs>

            <ellipse className="dp-floor" cx="216.5" cy="1010" rx="180" ry="72"/>
            <text className="dp-ghost-3d" x="211" y="435" textAnchor="middle" fontFamily="Inter, sans-serif" fontSize="315" fontWeight="600">3D</text>

            <ellipse className="dp-orbit-back" cx="216.5" cy="1010" rx="132" ry="34" transform="rotate(-13 216.5 1010)"/>

            <rect className="dp-pedestal" x="169" y="944" width="95" height="61" rx="12"/>
            <ellipse className="dp-pedestal" cx="216.5" cy="944" rx="47.5" ry="11"/>
            <ellipse className="dp-pedestal-rim" cx="216.5" cy="944" rx="47" ry="10"/>

            <image className="dp-robot" href="https://d2ol7oe51mr4n9.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/3fd6651e-dc6b-4339-a93a-fb627c0109e0.png" x="168.5" y="470" width="96" height="474" preserveAspectRatio="xMidYMax meet"/>

            <ellipse className="dp-orbit-front" cx="216.5" cy="1010" rx="132" ry="34" transform="rotate(-13 216.5 1010)"/>
            <circle className="dp-orbit-dot" cx="324" cy="997" r="4.2"/>
          </svg>
        </section>
      </div>
    </div>);
}
