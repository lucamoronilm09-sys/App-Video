/**
 * Formattazione errori tecnici per UX migliorata.
 * Riconosce errori comuni di FFmpeg/sistema e restituisce messaggi leggibili,
 * mantenendo i dettagli tecnici completi per il debug.
 */

export interface FormattedError {
  summary: string;
  technicalDetails: string;
  isKnownIssue: boolean;
}

const KNOWN_PATTERNS: Array<{ regex: RegExp; message: string }> = [
  {
    regex: /No such file or directory|File not found/i,
    message: "Impossibile trovare uno dei file multimediali. Potrebbe essere stato spostato o eliminato.",
  },
  {
    regex: /Permission denied/i,
    message: "Errore di permessi: impossibile leggere o scrivere su disco.",
  },
  {
    regex: /No space left on device|Disk full/i,
    message: "Spazio su disco esaurito. Libera spazio per continuare.",
  },
  {
    regex: /ffmpeg.*not found|command not found/i,
    message: "FFmpeg non è installato o non raggiungibile nel sistema.",
  },
  {
    regex: /Invalid data found when processing input|Corrupt input packet/i,
    message: "Uno dei file video/audio sembra corrotto o in un formato non supportato.",
  },
  {
    regex: /Encoder .* not found/i,
    message: "Codec video non supportato dall'installazione corrente di FFmpeg.",
  },
  {
    regex: /Broken pipe|Connection reset/i,
    message: "La connessione con il server è stata interrotta durante l'elaborazione.",
  },
  {
    regex: /Stream mapping failed|Output file does not contain any stream/i,
    message: "Errore nella configurazione del video. Verifica che tutti i media siano validi.",
  },
];

export function formatTechnicalError(error: any): FormattedError {
  if (!error) {
    return {
      summary: "Si è verificato un errore imprevisto.",
      technicalDetails: "",
      isKnownIssue: false,
    };
  }

  let rawMessage = "";
  if (typeof error === "string") {
    rawMessage = error;
  } else if (error instanceof Error) {
    rawMessage = error.message;
  } else if (error.response?.data?.detail) {
    rawMessage = error.response.data.detail;
  } else if (error.detail) {
    rawMessage = error.detail;
  } else {
    rawMessage = JSON.stringify(error);
  }

  // Cerca pattern noti
  for (const { regex, message } of KNOWN_PATTERNS) {
    if (regex.test(rawMessage)) {
      return {
        summary: message,
        technicalDetails: rawMessage,
        isKnownIssue: true,
      };
    }
  }

  // Errori generici di ffmpeg
  if (/exit code \d+|ffmpeg exit=/i.test(rawMessage)) {
    return {
      summary: "Errore durante la generazione del video. Consulta i dettagli tecnici sotto.",
      technicalDetails: rawMessage,
      isKnownIssue: false,
    };
  }

  return {
    summary: "Si è verificato un errore tecnico imprevisto.",
    technicalDetails: rawMessage,
    isKnownIssue: false,
  };
}
