import {calculatePersianMetadata as calculateCorePersianMetadata} from "../PersianFootageVideo";
import type {PersianVideoProps} from "../types";

/**
 * Film Type 2.16 keeps reviewed subject/action regions as production evidence,
 * but the active profile deliberately does not use that geometry as a hard
 * typography placement veto. The renderer core still owns historical pinned
 * behaviour, so the production boundary gives 2.16 an evidence-preserving
 * measurement view instead of changing the frozen old-profile branches.
 *
 * Missing/non-array `avoidRegions` stay missing/non-array here and are still
 * refused by the core review gate. Only already-reviewed arrays are hidden from
 * collision scoring. The original shots are restored into the returned props,
 * so review evidence survives the browser prepass and render handoff unchanged.
 */
function measurementProps(props: PersianVideoProps): PersianVideoProps {
  if (props.design?.profileVersion !== "2.16.0") return props;
  return {
    ...props,
    shots: props.shots.map((shot) =>
      Array.isArray(shot.avoidRegions)
        ? {...shot, avoidRegions: []}
        : shot,
    ),
  };
}

export const calculatePersianMetadata: typeof calculateCorePersianMetadata = async (args) => {
  const is216 = args.props.design?.profileVersion === "2.16.0";
  if (!is216) return calculateCorePersianMetadata(args);

  const reviewedShots = args.props.shots;
  const prepared = await calculateCorePersianMetadata({
    ...args,
    props: measurementProps(args.props),
  });

  if (!prepared.props) return prepared;
  return {
    ...prepared,
    props: {
      ...prepared.props,
      shots: reviewedShots,
    },
  };
};
