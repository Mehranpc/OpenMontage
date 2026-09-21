/** Film Type metadata prepass.
 *
 * Reviewed shot avoidRegions are authoritative placement evidence for every active
 * Film Type profile, including 2.16. Do not hide reviewed geometry from the core
 * fitter or rewrite subjectSafety after measurement: doing so made a preflighted
 * render capable of painting editorial type over a reviewed face.
 */
export {calculatePersianMetadata} from "../PersianFootageVideo";
