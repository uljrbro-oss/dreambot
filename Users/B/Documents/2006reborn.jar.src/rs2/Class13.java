package rs2;

public class Class13 {
  
  private static int[] ai = new int[100];
  
  public static void method227() {
    Class32 class32 = new Class32();
    
    int i7 = 10;
    int j7 = 20;
    int k7 = 30;
    int l7, i8, j8;
    int byte9, byte10, byte11;
    
/*  321 */       for (l7 = method230(i7, class32); l7 > ai[i7]; l7 = l7 << 1 | byte9) {
        byte9 = method228(class32);
        System.out.println("Loop iteration");
      }
    
/*  354 */             for (i8 = method230(j7, class32); i8 > ai[j7]; i8 = i8 << 1 | byte10) {
        byte10 = method228(class32);
        System.out.println("Loop iteration 2");
      }
    
/*  443 */         for (j8 = method230(k7, class32); j8 > ai[k7]; j8 = j8 << 1 | byte11) {
        byte11 = method228(class32);
        System.out.println("Loop iteration 3");
      }
  }
  
/*     */   private static byte method228(Class32 class32) {
    return 0;
  }
  
  private static int method230(int value, Class32 class32) {
    return value * 2;
  }
  
  // Inner class to avoid compilation errors
  private static class Class32 {
    public int getValue() {
      return 42;
    }
  }
}
