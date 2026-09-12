export default function PrivacyPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-8">
      <h1 className="text-xl font-semibold">Privacidad de datos de salud</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        MyFood es una aplicación autoalojada de uso personal/familiar. Cuando accede a
        Health Connect, lo hace solo para:
      </p>
      <ul className="list-disc pl-5 text-sm text-neutral-600 dark:text-neutral-400">
        <li>Leer peso, grasa corporal, pasos y calorías activas que tú decides importar.</li>
        <li>
          Escribir en Health Connect el agua y la comida que ya has registrado tú mismo en
          MyFood, para que otras apps conectadas (p. ej. Samsung Health) también lo vean.
        </li>
      </ul>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Ningún dato de salud sale del servidor donde tú mismo alojas MyFood ni se comparte
        con terceros. Puedes revocar el acceso en cualquier momento desde los ajustes de
        Health Connect de tu dispositivo.
      </p>
    </main>
  );
}
