/**
 * First-run guide.
 *
 * Without this, a new user lands on a dark chart surrounded by empty instrument panels with no
 * indication of what to press. That is fine for someone who built the thing and hopeless for
 * everyone else, so the guide states what the system is, what it will show them, and the three
 * steps to get there. It appears once and can be reopened from the masthead.
 */
import { ArrowRight, Compass, Ship, Snowflake, X } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

const STEPS = [
  {
    icon: Compass,
    title: 'Choose where you are sailing',
    body:
      'Pick a departure port and an Indian Antarctic station. Cape Town to Bharati is the default ' +
      'and the one worth seeing first.',
  },
  {
    icon: Snowflake,
    title: 'Press Plan',
    body:
      'The system works out two routes: the one a ship would sail with no ice information, and ' +
      'the one it recommends. It then sails both through the same physics so you can see the ' +
      'difference. This takes about 15 seconds of real computation.',
  },
  {
    icon: Ship,
    title: 'Press Start and watch',
    body:
      'The ship sails the plan hour by hour. Watch it slow down as it meets the ice, and watch ' +
      'the alerts appear when conditions turn dangerous.',
  },
];

export function Guide(): JSX.Element | null {
  const open = useAppStore((s) => s.guideOpen);
  const setGuideOpen = useAppStore((s) => s.setGuideOpen);
  const setScreen = useAppStore((s) => s.setScreen);

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-ground/90 p-4 backdrop-blur-sm">
      <div className="panel w-[640px] max-w-full p-5">
        <div className="flex items-start gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">
              Antarctic navigation, for ships that resupply Maitri and Bharati
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-2">
              Every austral summer India sends ships to its two Antarctic stations. They have about
              ninety days, and the sea ice decides whether they make it. This tool plans a route
              through that ice that is safe under international rules, and shows you what it costs
              in time, fuel and risk.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            className="ml-auto text-ink-3 hover:text-ink"
            onClick={() => setGuideOpen(false)}
          >
            <X size={16} />
          </button>
        </div>

        <ol className="mt-4 space-y-2">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <li key={title} className="flex gap-3 rounded-sm border border-hair bg-panel-2 p-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-accent/40 bg-accent/10 text-accent">
                <Icon size={14} />
              </div>
              <div>
                <div className="text-xs font-semibold text-ink">
                  <span className="text-accent">{i + 1}.</span> {title}
                </div>
                <p className="mt-0.5 text-2xs leading-relaxed text-ink-2">{body}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-4 rounded-sm border border-caution/40 bg-caution/10 p-3">
          <div className="text-2xs font-semibold uppercase tracking-[0.1em] text-caution">
            One thing to know before you trust a number
          </div>
          <p className="mt-1 text-2xs leading-relaxed text-ink-2">
            The ship physics, the international safety rules and the Antarctic coastline are real.
            The weather and sea-ice fields are <strong>simulated</strong> stand-ins for satellite
            data. Anything simulated is labelled as such throughout, and nothing here is a
            hard-coded result: every figure is computed when you press the button.
          </p>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <button
            type="button"
            className="btn btn-accent"
            onClick={() => {
              setGuideOpen(false);
              setScreen('planner');
            }}
          >
            Start with step 1
            <ArrowRight size={13} />
          </button>
          <button type="button" className="btn" onClick={() => setGuideOpen(false)}>
            Explore on my own
          </button>
          <span className="ml-auto text-2xs text-ink-3">Reopen any time from the Help button</span>
        </div>
      </div>
    </div>
  );
}
