package rs2;

public class client {
  
  private int anInt1054 = 0;
  private Stream stream = new Stream();
  public static boolean loggedIn = false;
  
  public static void main(String[] args) {
    System.out.println("RS2 Client starting...");
    client c = new client();
    c.method1();
  }
  
  public void method1() {
    int tabID = 1;
    
    // Decompiler artifact - stray this; statement
/*  6607 */     this; if (this.anInt1054 == tabID) {
      System.out.println("Tab ID matches");
/*  6609 */       this; this.stream.writeWordBigEndian(tabID);
    }
    
    System.out.println("Method 1 complete");
  }
  
  public void method2() {
    System.out.println("Logging in...");
    // Another decompiler artifact
/* 12089 */           this; loggedIn = true;
    System.out.println("Logged in: " + loggedIn);
  }
  
  // Inner class to avoid compilation errors
  private static class Stream {
    public void writeWordBigEndian(int value) {
      System.out.println("Writing: " + value);
    }
  }
}
