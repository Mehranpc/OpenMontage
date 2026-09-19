import {calculatePersianMetadata as calculateCorePersianMetadata} from "../PersianFootageVideo";
import type {PersianVideoProps} from "../types";

const SUBJECT_POLICY_WARNING =
  "Film Type 2.16: subject-region enforcement is OFF for typography placement; reviewed avoidRegions remain production evidence and do not move or refuse editorial text.";

function overlaps(
  moment: PersianVideoProps["moments"][number],
  shot: PersianVideoProps["shots"][number],
): boolean {
  return shot.startSeconds < moment.endSeconds && shot.endSeconds > moment.startSeconds;
}

/**
 * Convert a previously policy-decorated 2.16 layout back to the exact internal
 * form the frozen renderer core derives from reviewed-but-empty measurement
 * regions. This makes prepass -> saved props -> final render a stable round trip.
 */
function coreFilmType(props: PersianVideoProps): PersianVideoProps["filmType"] {
  const filmType = props.filmType;
  if (!filmType) return filmType;

  const moments = Object.fromEntries(
    Object.entries(filmType.moments).map(([id, layout]) => {
      const authored = props.moments.find((moment) => moment.id === id);
      const overlapping = authored
        ? props.shots.filter((shot) => overlaps(authored, shot))
        : [];
      const reviewed = overlapping.length > 0
        ? overlapping.every((shot) => Array.isArray(shot.avoidRegions))
        : false;
      const coreChecksSubject = authored?.kind !== "hook";
      return [
        id,
        {
          ...layout,
          subjectSafety: reviewed && coreChecksSubject
            ? "checked-against-supplied-regions" as const
            : "not-checked" as const,
        },
      ];
    }),
  );

  return {
    ...filmType,
    moments,
    warnings: filmType.warnings.filter((warning) => warning !== SUBJECT_POLICY_WARNING),
  };
}

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
    filmType: coreFilmType(props),
    shots: props.shots.map((shot) =>
      Array.isArray(shot.avoidRegions)
        ? {...shot, avoidRegions: []}
        : shot,
    ),
  };
}

function applySubjectPolicy(
  original: PersianVideoProps,
  prepared: PersianVideoProps,
): PersianVideoProps {
  const filmType = prepared.filmType;
  if (!filmType) return {...prepared, shots: original.shots};

  const moments = Object.fromEntries(
    Object.entries(filmType.moments).map(([id, layout]) => [
      id,
      {...layout, subjectSafety: "not-checked" as const},
    ]),
  );
  const warnings = filmType.warnings.includes(SUBJECT_POLICY_WARNING)
    ? filmType.warnings
    : [...filmType.warnings, SUBJECT_POLICY_WARNING];

  return {
    ...prepared,
    shots: original.shots,
    filmType: {...filmType, moments, warnings},
  };
}

export const calculatePersianMetadata: typeof calculateCorePersianMetadata = async (args) => {
  if (args.props.design?.profileVersion !== "2.16.0") {
    return calculateCorePersianMetadata(args);
  }

  const prepared = await calculateCorePersianMetadata({
    ...args,
    props: measurementProps(args.props),
  });
  if (!prepared.props) return prepared;

  return {
    ...prepared,
    props: applySubjectPolicy(args.props, prepared.props),
  };
};
