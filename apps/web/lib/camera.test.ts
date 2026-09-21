import { describe, expect, it } from "vitest";
import { cameraErrorMessage } from "@/lib/camera";

describe("cameraErrorMessage", () => {
  it("explains a denied permission and points to the manual entry", () => {
    expect(cameraErrorMessage("NotAllowedError: Permission denied")).toMatch(/permiso/);
    expect(cameraErrorMessage(new DOMException("Permission denied", "NotAllowedError"))).toMatch(/permiso/);
  });
  it("explains a missing camera", () => {
    expect(cameraErrorMessage("Error getting userMedia, error = NotFoundError: Requested device not found")).toMatch(/ninguna cámara/);
  });
  it("explains a busy camera", () => {
    expect(cameraErrorMessage("NotReadableError: Could not start video source")).toMatch(/otra aplicación/);
  });
  it("explains the insecure-context case", () => {
    expect(cameraErrorMessage("Only secure origins are allowed (https)")).toMatch(/seguras/);
  });
  it("never shows the generic browser error", () => {
    for (const err of ["algo raro", undefined, { code: 1 }, new Error("boom")]) {
      expect(cameraErrorMessage(err)).toMatch(/cámara/);
      expect(cameraErrorMessage(err)).toMatch(/a mano/);
    }
  });
});
