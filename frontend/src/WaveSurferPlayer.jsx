import React, { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { PlayIcon, PauseIcon } from '@heroicons/react/24/solid'

const WaveSurferPlayer = ({ url }) => {
  const containerRef = useRef(null)
  const wavesurfer = useRef(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return

    wavesurfer.current = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#94a3b8',
      progressColor: '#3b82f6',
      cursorColor: '#1d4ed8',
      barWidth: 2,
      barRadius: 3,
      height: 48,
      normalize: true,
      url: url,
    })

    wavesurfer.current.on('ready', () => {
      setIsReady(true)
    })

    wavesurfer.current.on('play', () => setIsPlaying(true))
    wavesurfer.current.on('pause', () => setIsPlaying(false))
    wavesurfer.current.on('finish', () => setIsPlaying(false))

    return () => {
      wavesurfer.current.destroy()
    }
  }, [url])

  const togglePlay = () => {
    if (wavesurfer.current) {
      wavesurfer.current.playPause()
    }
  }

  return (
    <div className="flex items-center gap-4 w-full bg-slate-50 border border-slate-200 rounded-lg p-2 pr-4 shadow-inner">
      <button
        onClick={togglePlay}
        disabled={!isReady}
        className="w-10 h-10 flex shrink-0 items-center justify-center bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow disabled:opacity-50 transition-colors"
      >
        {isPlaying ? <PauseIcon className="w-5 h-5" /> : <PlayIcon className="w-5 h-5 ml-1" />}
      </button>
      <div ref={containerRef} className="flex-1 overflow-hidden" />
    </div>
  )
}

export default WaveSurferPlayer
