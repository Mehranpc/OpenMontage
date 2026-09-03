/**
 * Footage layer — one shot, with its camera move and grade.
 *
 * ## Why `OffthreadVideo`
 *
 * Remotion's `<Video>` drives an HTML `<video>` element and asks it to seek to
 * each frame. Under concurrent rendering that seeking is unreliable: workers
 * compete, some frames arrive from the wrong timestamp, and the result is
 * intermittent duplicated or black frames that do not reproduce on a
 * single-threaded render. `OffthreadVideo` extracts frames with ffmpeg instead,
 * which is deterministic and the reason this pipeline can render concurrently.
 *
 * ## The grade
 *
 * Stock footage arrives with whatever contrast and saturation its author chose,
 * so a montage of unrelated clips looks like a montage of unrelated clips. A
 * consistent grade plus a vignette pulls them toward one look, and — more
 * practically — settling the frame's overall level is what keeps a clip shot on
 * snow or a white wall from reading as a hole in the video.
 *
 * The grade does *not* carry text legibility. That is the moment scrim's job, and
 * splitting the responsibility was deliberate: a grade heavy enough to guarantee
 * contrast for text is heavy enough to be visible as a grade on every frame,
 * including the ones with no text on them — which, in this pipeline, is most of
 * them. So the grade is light and always on, and the scrim is heavy and only
 * present under a moment.
 *
 * The grade is entirely static. A grade that animates draws attention to itself,
 * and a per-frame-varying vignette reads as flicker.
 */

import React from "react";
import { AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig } from "remotion";

import { cameraMove } from "../motion";
import type { PersianShot } from "../types";

export interface PersianFootageLayerProps {
  readonly shot: PersianShot;
  /** Resolved absolute or `staticFile()` URL for the clip. */
  readonly src: string;
  readonly durationFrames: number;
}

/**
 * Vignette strength. Enough to draw the eye inward, weak enough not to be
 * perceived as a vignette — past about 0.35 it reads as an effect. Lower than it
 * once was, because it is no longer doing double duty as text legibility.
 */
const VIGNETTE_ALPHA = 0.22;
/** Radius at which the vignette starts, as a percentage of the frame. */
const VIGNETTE_CLEAR_STOP = 58;

export const PersianFootageLayer: React.FC<PersianFootageLayerProps> = ({
  shot,
  src,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const camera = cameraMove(frame, durationFrames, shot.camera);

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          // The camera transform lives on a wrapper, not on the video element:
          // transforming the video itself can force a re-decode on some Chrome
          // builds, which is slow and occasionally drops a frame.
          transform: camera.transform,
          // Scaling from the centre keeps a push-in centred on the subject rather
          // than drifting toward a corner.
          transformOrigin: "center center",
        }}
      >
        <OffthreadVideo
          src={src}
          // `startFrom` is in frames of the SOURCE clip, so the in-point must be
          // converted with the source's own rate. Using the composition fps is
          // correct here only because the pipeline normalizes all footage to the
          // composition rate during download; the asset stage enforces that.
          startFrom={Math.round(shot.sourceInSeconds * fps)}
          // Cover, never contain: a letterboxed stock clip inside a vertical
          // frame is immediately recognisable as reframed landscape footage.
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          // Footage audio is never used — narration and music own the mix, and an
          // unmuted stock clip introduces room tone that fights them.
          muted
        />
      </AbsoluteFill>

      {/* Static grade. Two stacked layers: a radial vignette to seat the text,
          and a flat tonal wash to pull disparate clips toward one look. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at 50% 45%, rgba(0,0,0,0) ${VIGNETTE_CLEAR_STOP}%, rgba(0,0,0,${VIGNETTE_ALPHA}) 100%)`,
          pointerEvents: "none",
        }}
      />
      <AbsoluteFill
        style={{
          // Near-symmetrical, unlike its predecessor: that one was heavily
          // bottom-weighted because a caption panel lived down there, and with the
          // captions gone the same gradient just darkened the bottom third of
          // every shot for no reason. A slight bias remains at both edges, which
          // reads as exposure falloff rather than as an overlay.
          background:
            "linear-gradient(to bottom, rgba(11,11,12,0.14) 0%, rgba(11,11,12,0.03) 42%, rgba(11,11,12,0.18) 100%)",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};
