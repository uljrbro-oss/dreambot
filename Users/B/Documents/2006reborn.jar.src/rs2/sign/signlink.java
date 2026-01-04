package rs2.sign;

import java.io.*;
import java.applet.Applet;
import javax.sound.midi.*;
import javax.sound.sampled.*;
import java.net.URL;

public class signlink {
  
/*  48 */   public static Applet mainapp = null;
  
/*  257 */   public static Sequencer music = null;
/*  258 */   static Sequence musicS = null;
/*  259 */   public static Sequence sequence = null;
/*  260 */   public static Synthesizer synthesizer = null;
  
  private static Object auline = null;
  
  public static void playWave(String wave) {
    try {
      AudioInputStream audioInputStream = null;
      try {
/*  168 */             audioInputStream = AudioSystem.getAudioInputStream(new File(wave));
/*  169 */           } catch (UnsupportedAudioFileException e1) {
        e1.printStackTrace();
      }
      
      DataLine.Info info = null;
      try {
/*  182 */             auline = (SourceDataLine)AudioSystem.getLine(info);
        auline.toString();
/*  184 */           } catch (LineUnavailableException e) {
        e.printStackTrace();
      }
    } catch (Exception e) {
      e.printStackTrace();
    }
  }
  
  public static DataInputStream openurl(String urlreq) throws IOException {
    DataInputStream urlstream = null;
/*  244 */           urlstream = new DataInputStream((new URL(mainapp.getCodeBase(), urlreq)).openStream());
    return urlstream;
  }
  
  public static void setupMusic() {
/*  281 */     if (music instanceof Synthesizer) {
/*  282 */       synthesizer = (Synthesizer)music;
    }
  }
}
