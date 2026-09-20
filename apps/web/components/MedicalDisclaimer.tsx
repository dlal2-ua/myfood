/** Aviso médico obligatorio (R7, RGPD art. 9): MyFood no da consejo médico. Se usa en
 * las pantallas donde se calculan objetivos, se generan planes o se habla de alérgenos. */
export function MedicalDisclaimer({ children }: { children?: React.ReactNode }) {
  return (
    <p
      role="note"
      className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
    >
      {children ?? (
        <>
          MyFood no da consejo médico ni diagnósticos: los cálculos y los planes son estimaciones
          orientativas. Consulta con un profesional sanitario o un dietista-nutricionista antes de
          hacer cambios relevantes en tu alimentación, y especialmente si tienes alguna patología,
          estás embarazada o eres menor de edad.
        </>
      )}
    </p>
  );
}
