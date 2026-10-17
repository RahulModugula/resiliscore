import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "../../../contracts/parcel_score_schema.json";
import type { ParcelScoreResponse } from "@/types/resiliscore";

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile<ParcelScoreResponse>(schema);

export function parseParcel(data: unknown): ParcelScoreResponse {
  if (!validate(data)) throw new Error("API response does not match the parcel contract");
  return data;
}
