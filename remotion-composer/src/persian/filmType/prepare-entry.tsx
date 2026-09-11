import React from "react";
import {Composition, registerRoot} from "remotion";
import {PersianFootageVideo, calculatePersianMetadata, PERSIAN_FPS} from "../PersianFootageVideo";
import type {PersianVideoProps} from "../types";

/** Narrow registration for font/layout preparation; no unrelated compositions,
 * remote fonts or providers are imported. Paint is the real Persian component. */
const defaults: PersianVideoProps = {format:"vertical",durationSeconds:1,shots:[],moments:[],typographicBeats:[],captionMode:"sidecar_only",captions:[]};
const PrepareRoot: React.FC = () => <Composition id="PersianFilmTypePrepare"
  component={PersianFootageVideo} width={1080} height={1920} fps={PERSIAN_FPS}
  durationInFrames={PERSIAN_FPS} defaultProps={defaults} calculateMetadata={calculatePersianMetadata}/>;
registerRoot(PrepareRoot);
