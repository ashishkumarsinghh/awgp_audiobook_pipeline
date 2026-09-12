import { Link } from 'react-router-dom';
import { BookOpenIcon, MicrophoneIcon, SparklesIcon, UsersIcon } from '@heroicons/react/24/outline';

export default function Home() {
  return (
    <div className="bg-white">
      {/* Navigation */}
      <header className="absolute inset-x-0 top-0 z-50">
        <nav className="flex items-center justify-between p-6 lg:px-8" aria-label="Global">
          <div className="flex lg:flex-1">
            <a href="#" className="-m-1.5 p-1.5 flex items-center gap-2">
              <span className="sr-only">AWGP Audiobook</span>
              <BookOpenIcon className="h-8 w-8 text-blue-600" />
              <span className="font-bold text-xl text-slate-900">AWGP Audio</span>
            </a>
          </div>
          <div className="flex flex-1 justify-end gap-4">
            <Link to="/login" className="text-sm font-semibold leading-6 text-slate-900">
              Log in <span aria-hidden="true">→</span>
            </Link>
            <Link to="/register" className="text-sm font-semibold leading-6 text-white bg-blue-600 hover:bg-blue-500 px-3 py-1 rounded-md">
              Join as Volunteer
            </Link>
          </div>
        </nav>
      </header>

      {/* Hero Section (Adapted from TailwindUI OSS) */}
      <div className="relative isolate px-6 pt-14 lg:px-8">
        <div className="mx-auto max-w-2xl py-32 sm:py-48 lg:py-56">
          <div className="text-center">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-6xl">
              Preserving Spiritual Heritage Through Voice
            </h1>
            <p className="mt-6 text-lg leading-8 text-slate-600">
              Join the open-source initiative to digitize thousands of vintage spiritual texts, shlokas, and mantras into high-fidelity, human-like audiobooks.
            </p>
            <div className="mt-10 flex items-center justify-center gap-x-6">
              <Link
                to="/register"
                className="rounded-md bg-blue-600 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
              >
                Start Volunteering
              </Link>
              <a href="#how-it-works" className="text-sm font-semibold leading-6 text-slate-900">
                Learn how it works <span aria-hidden="true">↓</span>
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* Feature Section (Adapted from OSS Libraries) */}
      <div id="how-it-works" className="py-24 sm:py-32 bg-slate-50">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div className="mx-auto max-w-2xl lg:text-center">
            <h2 className="text-base font-semibold leading-7 text-blue-600">The Pipeline</h2>
            <p className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
              A 6-Stage Open Source Pipeline
            </p>
            <p className="mt-6 text-lg leading-8 text-slate-600">
              We leverage Gemini OCR and advanced TTS models, backed by human editorial oversight, to ensure precise pronunciation of Sanskrit and Hindi texts.
            </p>
          </div>
          <div className="mx-auto mt-16 max-w-2xl sm:mt-20 lg:mt-24 lg:max-w-4xl">
            <dl className="grid max-w-xl grid-cols-1 gap-x-8 gap-y-10 lg:max-w-none lg:grid-cols-2 lg:gap-y-16">
              {[
                {
                  name: 'Gemini Vision OCR',
                  description: 'State-of-the-art text extraction from vintage scanned PDFs with automatic layout retention.',
                  icon: SparklesIcon,
                },
                {
                  name: 'Sanskrit Phonetics Engine',
                  description: 'A custom dictionary mapping specific bīja mantras to their exact phonetic approximations to prevent robotic reading.',
                  icon: BookOpenIcon,
                },
                {
                  name: 'Edge-TTS Synthesis',
                  description: 'Generating raw audio chunks using advanced neural voices to emulate human narrative pacing.',
                  icon: MicrophoneIcon,
                },
                {
                  name: 'Volunteer Oversight',
                  description: 'A dedicated dashboard for volunteers to audit, re-generate, and stitch audio chunks together.',
                  icon: UsersIcon,
                },
              ].map((feature) => (
                <div key={feature.name} className="relative pl-16">
                  <dt className="text-base font-semibold leading-7 text-slate-900">
                    <div className="absolute left-0 top-0 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600">
                      <feature.icon className="h-6 w-6 text-white" aria-hidden="true" />
                    </div>
                    {feature.name}
                  </dt>
                  <dd className="mt-2 text-base leading-7 text-slate-600">{feature.description}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}
