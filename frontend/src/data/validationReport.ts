import snapshot from "../../../contracts/validation_report.json";
import { parseValidationReport } from "@/lib/validation";

// Bundle the shared report so model review remains available without the API.
export const validationReport = parseValidationReport(snapshot);
